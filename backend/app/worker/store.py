"""Database operations used by the worker: claim due monitors, record results."""

import logging
from dataclasses import dataclass

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Check, Incident, Monitor
from app.worker.checker import CheckResult
from app.worker.state import Event, MonitorState, apply_result

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ClaimedMonitor:
    """What a check needs, copied out of the DB so no ORM object crosses tasks."""

    id: int
    url: str
    interval_seconds: int


async def claim_due(session: AsyncSession, limit: int) -> list[ClaimedMonitor]:
    """Atomically pick up to `limit` due monitors and lease them.

    One statement:
        UPDATE monitors SET next_check_at = now() + interval
        WHERE id IN (SELECT id ... WHERE due ... FOR UPDATE SKIP LOCKED LIMIT n)
        RETURNING id, url, interval_seconds

    - SKIP LOCKED: concurrent workers never pick the same rows.
    - The lease (next_check_at pushed forward) means a crashed worker can't cause a
      tight re-check loop; the real next time is set when the result is recorded.
    """
    due = (
        select(Monitor.id)
        .where(~Monitor.is_paused, Monitor.next_check_at <= func.now())  # matches ix_monitors_due
        .order_by(Monitor.next_check_at)
        .limit(limit)
        .with_for_update(skip_locked=True)
    )
    stmt = (
        update(Monitor)
        .where(Monitor.id.in_(due))
        .values(next_check_at=func.now() + func.make_interval(0, 0, 0, 0, 0, 0, Monitor.interval_seconds))
        .returning(Monitor.id, Monitor.url, Monitor.interval_seconds)
        .execution_options(synchronize_session=False)
    )
    rows = (await session.execute(stmt)).all()
    await session.commit()
    return [ClaimedMonitor(id=r.id, url=r.url, interval_seconds=r.interval_seconds) for r in rows]


async def record_result(
    session: AsyncSession,
    claimed: ClaimedMonitor,
    result: CheckResult,
    *,
    failure_threshold: int,
    retry_interval_seconds: int,
) -> Event | None:
    """Store a check result and apply the state transition, in one transaction.

    The monitor row is locked (SELECT ... FOR UPDATE) so an API edit can't interleave.
    The result is discarded if, while the check was running, the monitor was
    deleted, paused, or its URL changed: it would describe something that no longer
    applies and would overwrite the reset done by the API.
    """
    monitor = await session.get(Monitor, claimed.id, with_for_update=True, populate_existing=True)
    if monitor is None or monitor.is_paused or monitor.url != claimed.url:
        await session.rollback()  # release the lock
        logger.info("Discarding stale result for monitor %s (deleted, paused or URL changed)", claimed.id)
        return None

    session.add(
        Check(
            monitor_id=monitor.id,
            checked_at=result.checked_at,
            is_up=result.is_up,
            status_code=result.status_code,
            response_time_ms=result.response_time_ms,
            error_type=result.error_type,
            error_message=result.error_message,
        )
    )

    transition = apply_result(
        MonitorState(monitor.status, monitor.consecutive_failures, monitor.failing_since),
        result,
        interval_seconds=monitor.interval_seconds,  # current value, in case it was edited mid-check
        failure_threshold=failure_threshold,
        retry_interval_seconds=retry_interval_seconds,
    )

    monitor.status = transition.state.status
    monitor.consecutive_failures = transition.state.consecutive_failures
    monitor.failing_since = transition.state.failing_since
    monitor.next_check_at = transition.next_check_at
    monitor.last_checked_at = result.checked_at
    monitor.last_status_code = result.status_code
    monitor.last_response_time_ms = result.response_time_ms
    monitor.last_error_type = result.error_type

    if transition.close_incident:
        await session.execute(
            update(Incident)
            .where(Incident.monitor_id == monitor.id, Incident.resolved_at.is_(None))
            .values(resolved_at=result.checked_at)
        )
    if transition.open_incident:
        session.add(
            Incident(
                monitor_id=monitor.id,
                started_at=transition.state.failing_since,
                error_type=result.error_type,
                error_message=result.error_message,
            )
        )

    await session.commit()
    return transition.event
