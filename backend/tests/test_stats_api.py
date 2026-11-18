"""Stats endpoints and the uptime / response-time math (app/services/stats.py)."""

from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Check, ErrorType, Incident, Monitor


@pytest.fixture(autouse=True)
def _dns(fake_dns):
    return fake_dns


async def new_monitor(session: AsyncSession, name: str = "m") -> Monitor:
    m = Monitor(name=name, url="https://example.com", interval_seconds=60)
    session.add(m)
    await session.commit()
    return m


def check(m: Monitor, ago: timedelta, up: bool = True, ms: int | None = 100, now: datetime | None = None) -> Check:
    return Check(
        monitor_id=m.id,
        checked_at=(now or datetime.now(UTC)) - ago,
        is_up=up,
        status_code=200 if up else 503,
        response_time_ms=ms,
        error_type=None if up else ErrorType.HTTP_5XX,
        error_message=None if up else "HTTP 503",
    )


async def add(session: AsyncSession, *checks: Check) -> None:
    session.add_all(checks)
    await session.commit()


# ---------- uptime & averages ----------


async def test_uptime_and_average_response_time(client: AsyncClient, session: AsyncSession) -> None:
    m = await new_monitor(session)
    h = timedelta(hours=1)
    await add(
        session,
        # last 24h: 3 up (100, 200, 300 ms) + 1 down  -> 75 %, avg 200 ms
        check(m, 1 * h, ms=100),
        check(m, 2 * h, ms=200),
        check(m, 3 * h, ms=300),
        check(m, 4 * h, up=False, ms=5000),  # failures don't count towards the average
        # 2-6 days ago: 4 more down -> 7d = 3 up / 8 total = 37.5 %
        *[check(m, timedelta(days=d), up=False) for d in (2, 3, 4, 6)],
        # older than 7 days: ignored entirely
        check(m, timedelta(days=8), up=False),
    )

    stats = (await client.get(f"/api/monitors/{m.id}")).json()["stats"]
    assert stats["uptime_24h"] == 75.0
    assert stats["uptime_7d"] == 37.5
    assert stats["avg_response_ms_24h"] == 200


async def test_stats_are_null_without_checks(client: AsyncClient, session: AsyncSession) -> None:
    m = await new_monitor(session)
    data = (await client.get(f"/api/monitors/{m.id}")).json()
    assert data["uptime_24h"] is None
    assert data["stats"]["uptime_24h"] is None
    assert data["stats"]["uptime_7d"] is None
    assert data["stats"]["avg_response_ms_24h"] is None


async def test_uptime_rounds_to_two_decimals(client: AsyncClient, session: AsyncSession) -> None:
    m = await new_monitor(session)
    await add(session, check(m, timedelta(minutes=1)), check(m, timedelta(minutes=2)),
              check(m, timedelta(minutes=3), up=False))
    assert (await client.get(f"/api/monitors/{m.id}")).json()["stats"]["uptime_24h"] == 66.67


async def test_list_includes_uptime_per_monitor(client: AsyncClient, session: AsyncSession) -> None:
    healthy = await new_monitor(session, "healthy")
    flaky = await new_monitor(session, "flaky")
    silent = await new_monitor(session, "no checks")
    await add(
        session,
        check(healthy, timedelta(minutes=5)),
        check(flaky, timedelta(minutes=5)),
        check(flaky, timedelta(minutes=10), up=False),
        check(healthy, timedelta(days=2), up=False),  # outside 24h: ignored
    )
    by_name = {m["name"]: m["uptime_24h"] for m in (await client.get("/api/monitors")).json()}
    assert by_name == {"healthy": 100.0, "flaky": 50.0, "no checks": None}
    assert silent.id  # (created, just has no data)


# ---------- response-time buckets ----------


async def test_response_times_24h_groups_into_5_minute_buckets(client: AsyncClient, session: AsyncSession) -> None:
    m = await new_monitor(session)
    # Pick a bucket start an hour ago, aligned to a 5-minute UTC boundary.
    now = datetime.now(UTC)
    start = datetime.fromtimestamp((int((now - timedelta(hours=1)).timestamp()) // 300) * 300, UTC)
    prev = start - timedelta(minutes=5)
    await add(
        session,
        Check(monitor_id=m.id, checked_at=start + timedelta(seconds=10), is_up=True, response_time_ms=100),
        Check(monitor_id=m.id, checked_at=start + timedelta(seconds=70), is_up=True, response_time_ms=300),
        Check(monitor_id=m.id, checked_at=start + timedelta(seconds=130), is_up=False, error_type=ErrorType.TIMEOUT),
        Check(monitor_id=m.id, checked_at=prev + timedelta(seconds=5), is_up=False, error_type=ErrorType.DNS),
    )

    data = (await client.get(f"/api/monitors/{m.id}/response-times?range=24h")).json()
    assert data["range"] == "24h" and data["bucket_seconds"] == 300
    points = data["points"]
    assert [datetime.fromisoformat(p["t"]) for p in points] == [prev, start]  # ordered, empty buckets omitted
    assert points[0] == {"t": points[0]["t"], "avg_ms": None, "max_ms": None, "checks": 1, "failures": 1}
    assert points[1] == {"t": points[1]["t"], "avg_ms": 200, "max_ms": 300, "checks": 3, "failures": 1}


async def test_response_times_7d_uses_hourly_buckets_and_window(client: AsyncClient, session: AsyncSession) -> None:
    m = await new_monitor(session)
    await add(session, check(m, timedelta(days=3)), check(m, timedelta(days=9)))  # 9 days: outside 7d
    data = (await client.get(f"/api/monitors/{m.id}/response-times?range=7d")).json()
    assert data["bucket_seconds"] == 3600
    assert len(data["points"]) == 1
    t = datetime.fromisoformat(data["points"][0]["t"])
    assert t.minute == 0 and t.second == 0  # aligned to the hour


async def test_response_times_rejects_unknown_range(client: AsyncClient, session: AsyncSession) -> None:
    m = await new_monitor(session)
    assert (await client.get(f"/api/monitors/{m.id}/response-times?range=30d")).status_code == 422


# ---------- recent checks ----------


async def test_checks_newest_first_with_limit_and_paging(client: AsyncClient, session: AsyncSession) -> None:
    m = await new_monitor(session)
    now = datetime.now(UTC)
    await add(session, *[check(m, timedelta(minutes=i), now=now) for i in range(5)])  # 0..4 min ago

    page1 = (await client.get(f"/api/monitors/{m.id}/checks?limit=2")).json()
    times1 = [datetime.fromisoformat(c["checked_at"]) for c in page1]
    assert times1 == [now, now - timedelta(minutes=1)]
    assert set(page1[0]) == {"id", "checked_at", "is_up", "status_code", "response_time_ms",
                             "error_type", "error_message"}

    oldest = page1[-1]["checked_at"]
    page2 = (await client.get(f"/api/monitors/{m.id}/checks", params={"limit": 2, "before": oldest})).json()
    assert [datetime.fromisoformat(c["checked_at"]) for c in page2] == [
        now - timedelta(minutes=2),
        now - timedelta(minutes=3),
    ]


async def test_checks_limit_is_bounded(client: AsyncClient, session: AsyncSession) -> None:
    m = await new_monitor(session)
    assert (await client.get(f"/api/monitors/{m.id}/checks?limit=0")).status_code == 422
    assert (await client.get(f"/api/monitors/{m.id}/checks?limit=501")).status_code == 422


# ---------- incidents ----------


async def test_incident_history_newest_first_with_durations(client: AsyncClient, session: AsyncSession) -> None:
    m = await new_monitor(session)
    now = datetime.now(UTC)
    session.add_all(
        [
            Incident(monitor_id=m.id, started_at=now - timedelta(days=2),
                     resolved_at=now - timedelta(days=2) + timedelta(minutes=15), error_type=ErrorType.TIMEOUT),
            Incident(monitor_id=m.id, started_at=now - timedelta(minutes=10), error_type=ErrorType.HTTP_5XX),
        ]
    )
    await session.commit()

    incidents = (await client.get(f"/api/monitors/{m.id}/incidents")).json()
    assert [i["error_type"] for i in incidents] == ["http_5xx", "timeout"]
    ongoing, resolved = incidents
    assert ongoing["resolved_at"] is None
    assert 595 <= ongoing["duration_seconds"] <= 605  # ~10 min and counting
    assert resolved["duration_seconds"] == 900  # exactly 15 min


# ---------- 404s ----------


@pytest.mark.parametrize("path", ["checks", "response-times", "incidents"])
async def test_stats_endpoints_404_for_unknown_monitor(client: AsyncClient, path: str) -> None:
    resp = await client.get(f"/api/monitors/999999/{path}")
    assert resp.status_code == 404
    assert resp.json() == {"detail": "Monitor not found"}
