"""Worker DB operations (app/worker/store.py) against the real test database."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Check, ErrorType, Incident, Monitor, MonitorStatus
from app.worker.checker import CheckResult
from app.worker.state import Event
from app.worker.store import ClaimedMonitor, claim_due, record_result


async def add_monitor(session: AsyncSession, *, due_in: int = -1, paused: bool = False, interval: int = 60) -> Monitor:
    m = Monitor(
        name="m",
        url="https://example.com",
        interval_seconds=interval,
        is_paused=paused,
        next_check_at=datetime.now(UTC) + timedelta(seconds=due_in),
    )
    session.add(m)
    await session.commit()
    return m


def claimed(m: Monitor) -> ClaimedMonitor:
    return ClaimedMonitor(id=m.id, url=m.url, interval_seconds=m.interval_seconds)


async def record(session: AsyncSession, m: Monitor, result: CheckResult):
    return await record_result(session, claimed(m), result, failure_threshold=3, retry_interval_seconds=30)


def ok(at: datetime) -> CheckResult:
    return CheckResult(at, is_up=True, status_code=200, response_time_ms=120)


def fail(at: datetime) -> CheckResult:
    return CheckResult(at, is_up=False, status_code=503, response_time_ms=50,
                       error_type=ErrorType.HTTP_5XX, error_message="HTTP 503")


# ---------- claim_due ----------


async def test_claim_returns_only_due_active_monitors(session: AsyncSession) -> None:
    due = await add_monitor(session, due_in=-5)
    await add_monitor(session, due_in=+600)  # not due yet
    await add_monitor(session, due_in=-5, paused=True)  # paused

    got = await claim_due(session, limit=10)
    assert [c.id for c in got] == [due.id]


async def test_claim_leases_monitor_so_it_is_not_claimed_twice(session: AsyncSession) -> None:
    m = await add_monitor(session, due_in=-5, interval=300)
    assert len(await claim_due(session, limit=10)) == 1
    assert await claim_due(session, limit=10) == []  # lease pushed next_check_at forward

    await session.refresh(m)
    lease = (m.next_check_at - datetime.now(UTC)).total_seconds()
    assert 290 < lease <= 300


async def test_claim_respects_limit_and_picks_most_overdue_first(session: AsyncSession) -> None:
    older = await add_monitor(session, due_in=-100)
    await add_monitor(session, due_in=-10)
    got = await claim_due(session, limit=1)
    assert [c.id for c in got] == [older.id]


# ---------- record_result ----------


async def test_success_stores_check_and_marks_up(session: AsyncSession) -> None:
    m = await add_monitor(session)
    t = datetime.now(UTC)
    assert await record(session, m, ok(t)) is None

    await session.refresh(m)
    assert m.status == MonitorStatus.UP
    assert (m.last_checked_at, m.last_status_code, m.last_response_time_ms) == (t, 200, 120)
    assert m.next_check_at == t + timedelta(seconds=60)
    assert await session.scalar(select(func.count()).select_from(Check).where(Check.monitor_id == m.id)) == 1


async def test_three_failures_open_incident_then_recovery_closes_it(session: AsyncSession) -> None:
    m = await add_monitor(session)
    t0 = datetime.now(UTC)

    assert await record(session, m, fail(t0)) is None
    assert await record(session, m, fail(t0 + timedelta(seconds=30))) is None
    await session.refresh(m)
    assert m.status == MonitorStatus.PENDING and m.consecutive_failures == 2
    assert m.next_check_at == t0 + timedelta(seconds=60)  # fast retry: 30s after the 2nd failure

    assert await record(session, m, fail(t0 + timedelta(seconds=60))) == Event.DOWN
    incident = (await session.execute(select(Incident).where(Incident.monitor_id == m.id))).scalar_one()
    assert incident.started_at == t0  # first failure, not confirmation time
    assert incident.resolved_at is None
    assert incident.error_type == ErrorType.HTTP_5XX

    recovered_at = t0 + timedelta(minutes=5)
    assert await record(session, m, ok(recovered_at)) == Event.RECOVERED
    await session.refresh(incident)
    assert incident.resolved_at == recovered_at
    await session.refresh(m)
    assert m.status == MonitorStatus.UP and m.consecutive_failures == 0 and m.failing_since is None


@pytest.mark.parametrize("change", ["paused", "url_changed", "deleted"])
async def test_stale_result_is_discarded(session: AsyncSession, change: str) -> None:
    m = await add_monitor(session)
    snapshot = claimed(m)  # what the worker saw when it claimed the monitor

    # ...the user edits the monitor while the check is in flight...
    if change == "paused":
        m.is_paused = True
    elif change == "url_changed":
        m.url = "https://example.org"
    else:
        await session.delete(m)
    await session.commit()

    event = await record_result(session, snapshot, fail(datetime.now(UTC)),
                                failure_threshold=3, retry_interval_seconds=30)
    assert event is None
    assert await session.scalar(select(func.count()).select_from(Check).where(Check.monitor_id == snapshot.id)) == 0
    if change != "deleted":
        await session.refresh(m)
        assert m.consecutive_failures == 0
