from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Check, ErrorType, Incident, Monitor, MonitorStatus


@pytest.fixture(autouse=True)
def _dns(fake_dns):
    """No real DNS in API tests; every host resolves to a public IP unless overridden."""
    return fake_dns


async def create(client: AsyncClient, **overrides) -> dict:
    body = {"name": "Example", "url": "https://example.com", "interval_seconds": 60} | overrides
    resp = await client.post("/api/monitors", json=body)
    assert resp.status_code == 201, resp.text
    return resp.json()


async def make_down_with_open_incident(session: AsyncSession, monitor_id: int) -> datetime:
    """Put a monitor into a confirmed-DOWN state, like the worker will in Stage 3."""
    started = datetime.now(UTC) - timedelta(minutes=5)
    monitor = await session.get(Monitor, monitor_id)
    monitor.status = MonitorStatus.DOWN
    monitor.consecutive_failures = 3
    monitor.failing_since = started
    monitor.last_checked_at = datetime.now(UTC)
    monitor.last_status_code = 503
    monitor.last_error_type = ErrorType.HTTP_5XX
    session.add(Incident(monitor_id=monitor_id, started_at=started, error_type=ErrorType.HTTP_5XX))
    await session.commit()
    return started


# ---------- create / read ----------


async def test_create_returns_new_pending_monitor(client: AsyncClient) -> None:
    data = await create(client, name="  My site  ", url="HTTPS://Example.com/health")
    assert data["id"] > 0
    assert data["name"] == "My site"  # trimmed
    assert data["url"] == "https://example.com/health"  # normalized
    assert data["status"] == "pending"
    assert data["display_status"] == "pending"
    assert data["is_paused"] is False
    assert data["last_checked_at"] is None
    assert data["uptime_24h"] is None


async def test_list_returns_created_monitors(client: AsyncClient) -> None:
    a = await create(client, name="A")
    b = await create(client, name="B", url="https://example.org")
    resp = await client.get("/api/monitors")
    assert resp.status_code == 200
    assert [m["id"] for m in resp.json()] == [a["id"], b["id"]]


async def test_get_detail_includes_stats(client: AsyncClient) -> None:
    m = await create(client)
    resp = await client.get(f"/api/monitors/{m['id']}")
    assert resp.status_code == 200
    assert resp.json()["stats"] == {
        "uptime_24h": None,
        "uptime_7d": None,
        "avg_response_ms_24h": None,
        "open_incident": None,
    }


async def test_get_detail_shows_open_incident(client: AsyncClient, session: AsyncSession) -> None:
    m = await create(client)
    await make_down_with_open_incident(session, m["id"])
    data = (await client.get(f"/api/monitors/{m['id']}")).json()
    assert data["display_status"] == "down"
    incident = data["stats"]["open_incident"]
    assert incident["resolved_at"] is None
    assert incident["error_type"] == "http_5xx"
    assert 290 <= incident["duration_seconds"] <= 310  # started ~5 min ago


@pytest.mark.parametrize("method", ["get", "patch", "delete"])
async def test_unknown_monitor_is_404(client: AsyncClient, method: str) -> None:
    kwargs = {"json": {"name": "x"}} if method == "patch" else {}
    resp = await getattr(client, method)("/api/monitors/999999", **kwargs)
    assert resp.status_code == 404
    assert resp.json() == {"detail": "Monitor not found"}


# ---------- validation (422) ----------


@pytest.mark.parametrize(
    ("body", "field"),
    [
        ({"name": "x", "url": "https://example.com", "interval_seconds": 45}, "interval_seconds"),
        ({"name": "", "url": "https://example.com"}, "name"),
        ({"name": "x" * 101, "url": "https://example.com"}, "name"),
        ({"name": "x", "url": "ftp://example.com"}, "url"),
        ({"name": "x", "url": "http://127.0.0.1:5432"}, "url"),
        ({"name": "x"}, "url"),
        ({"name": "x", "url": "https://example.com", "unexpected": 1}, "unexpected"),
    ],
)
async def test_create_validation_errors(client: AsyncClient, body: dict, field: str) -> None:
    resp = await client.post("/api/monitors", json=body)
    assert resp.status_code == 422
    assert field in [e["loc"][-1] for e in resp.json()["detail"]]


async def test_create_rejects_host_resolving_to_private_ip(client: AsyncClient, fake_dns) -> None:
    fake_dns["db.internal.example"] = ["10.0.0.5"]
    resp = await client.post("/api/monitors", json={"name": "x", "url": "http://db.internal.example"})
    assert resp.status_code == 422
    error = resp.json()["detail"][0]
    assert error["loc"] == ["body", "url"]
    assert error["msg"] == "Private or local addresses are not allowed"


async def test_create_accepts_unresolvable_host(client: AsyncClient, fake_dns) -> None:
    fake_dns["this-site-does-not-exist.invalid"] = []
    await create(client, url="https://this-site-does-not-exist.invalid")


async def test_patch_rejects_explicit_null(client: AsyncClient) -> None:
    m = await create(client)
    resp = await client.patch(f"/api/monitors/{m['id']}", json={"name": None})
    assert resp.status_code == 422
    assert resp.json()["detail"][0]["msg"] == "name cannot be null"


# ---------- update semantics (SPEC §6 "Edits and pause") ----------


async def test_patch_name_only_keeps_check_state(client: AsyncClient, session: AsyncSession) -> None:
    m = await create(client)
    await make_down_with_open_incident(session, m["id"])
    resp = await client.patch(f"/api/monitors/{m['id']}", json={"name": "Renamed"})
    data = resp.json()
    assert resp.status_code == 200
    assert data["name"] == "Renamed"
    assert data["status"] == "down"
    assert data["consecutive_failures"] == 3


async def test_pause_resets_state_and_closes_incident(client: AsyncClient, session: AsyncSession) -> None:
    m = await create(client)
    await make_down_with_open_incident(session, m["id"])

    data = (await client.patch(f"/api/monitors/{m['id']}", json={"is_paused": True})).json()
    assert data["is_paused"] is True
    assert data["display_status"] == "paused"
    assert data["status"] == "pending"
    assert data["consecutive_failures"] == 0
    assert data["last_status_code"] == 503  # last known result is kept on pause

    incident = (await session.execute(select(Incident).where(Incident.monitor_id == m["id"]))).scalar_one()
    assert incident.resolved_at is not None


async def test_resume_schedules_immediate_check(client: AsyncClient) -> None:
    m = await create(client)
    await client.patch(f"/api/monitors/{m['id']}", json={"is_paused": True})
    before = datetime.now(UTC)
    data = (await client.patch(f"/api/monitors/{m['id']}", json={"is_paused": False})).json()
    assert data["is_paused"] is False
    assert data["display_status"] == "pending"
    assert datetime.fromisoformat(data["next_check_at"]) >= before - timedelta(seconds=1)


async def test_url_change_resets_state_and_last_result(client: AsyncClient, session: AsyncSession) -> None:
    m = await create(client)
    await make_down_with_open_incident(session, m["id"])

    data = (await client.patch(f"/api/monitors/{m['id']}", json={"url": "https://example.org"})).json()
    assert data["url"] == "https://example.org"
    assert data["status"] == "pending"
    assert data["consecutive_failures"] == 0
    assert data["last_checked_at"] is None
    assert data["last_status_code"] is None
    assert data["last_error_type"] is None
    open_incident = (await client.get(f"/api/monitors/{m['id']}")).json()["stats"]["open_incident"]
    assert open_incident is None


async def test_url_change_to_private_address_is_rejected(client: AsyncClient, fake_dns) -> None:
    m = await create(client)
    fake_dns["sneaky.example"] = ["192.168.0.10"]
    resp = await client.patch(f"/api/monitors/{m['id']}", json={"url": "http://sneaky.example"})
    assert resp.status_code == 422
    assert (await client.get(f"/api/monitors/{m['id']}")).json()["url"] == "https://example.com"


async def test_interval_change_reschedules_from_last_check(client: AsyncClient, session: AsyncSession) -> None:
    m = await create(client, interval_seconds=3600)
    last = datetime.now(UTC) - timedelta(seconds=10)
    monitor = await session.get(Monitor, m["id"])
    monitor.last_checked_at = last
    await session.commit()

    data = (await client.patch(f"/api/monitors/{m['id']}", json={"interval_seconds": 300})).json()
    assert data["interval_seconds"] == 300
    assert datetime.fromisoformat(data["next_check_at"]) == last + timedelta(seconds=300)


async def test_failing_but_not_confirmed_shows_as_failing(client: AsyncClient, session: AsyncSession) -> None:
    m = await create(client)
    monitor = await session.get(Monitor, m["id"])
    monitor.status = MonitorStatus.UP
    monitor.consecutive_failures = 1
    await session.commit()
    assert (await client.get(f"/api/monitors/{m['id']}")).json()["display_status"] == "failing"


# ---------- delete ----------


async def test_delete_cascades_checks_and_incidents(client: AsyncClient, session: AsyncSession) -> None:
    m = await create(client)
    session.add(Check(monitor_id=m["id"], checked_at=datetime.now(UTC), is_up=True, status_code=200))
    await make_down_with_open_incident(session, m["id"])

    resp = await client.delete(f"/api/monitors/{m['id']}")
    assert resp.status_code == 204
    assert (await client.get(f"/api/monitors/{m['id']}")).status_code == 404

    for model in (Check, Incident):
        count = await session.scalar(select(func.count()).select_from(model).where(model.monitor_id == m["id"]))
        assert count == 0
