"""Business rules for editing monitors (SPEC §6, "Edits and pause").

Kept out of the router so the rules are in one place and easy to test.
"""

from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Incident, Monitor, MonitorStatus
from app.schemas import MonitorUpdate


async def get_open_incident(session: AsyncSession, monitor_id: int) -> Incident | None:
    result = await session.execute(
        select(Incident).where(Incident.monitor_id == monitor_id, Incident.resolved_at.is_(None))
    )
    return result.scalar_one_or_none()


async def reset_check_state(session: AsyncSession, monitor: Monitor, now: datetime, *, clear_last_result: bool) -> None:
    """Forget the current up/down state: used on pause and on URL change.

    Any open incident is closed at `now`. Otherwise a paused monitor would
    accumulate "downtime" while nobody is checking it.
    """
    await session.execute(
        update(Incident)
        .where(Incident.monitor_id == monitor.id, Incident.resolved_at.is_(None))
        .values(resolved_at=now)
    )
    monitor.status = MonitorStatus.PENDING
    monitor.consecutive_failures = 0
    monitor.failing_since = None
    if clear_last_result:
        # The last result belonged to a different URL, so it would be misleading now.
        monitor.last_checked_at = None
        monitor.last_status_code = None
        monitor.last_response_time_ms = None
        monitor.last_error_type = None


async def apply_update(session: AsyncSession, monitor: Monitor, changes: MonitorUpdate) -> None:
    """Apply a partial update with its side effects. Does not commit."""
    now = datetime.now(UTC)
    fields = changes.model_fields_set

    if "name" in fields:
        monitor.name = changes.name

    url_changed = "url" in fields and changes.url != monitor.url
    if url_changed:
        monitor.url = changes.url
        await reset_check_state(session, monitor, now, clear_last_result=True)
        monitor.next_check_at = now  # check the new URL right away

    if "interval_seconds" in fields and changes.interval_seconds != monitor.interval_seconds:
        monitor.interval_seconds = changes.interval_seconds
        if not url_changed:
            # Keep the rhythm: next check is one *new* interval after the last one.
            # (If that's already in the past, the monitor is simply due now.)
            base = monitor.last_checked_at or now
            monitor.next_check_at = base + timedelta(seconds=monitor.interval_seconds)

    if "is_paused" in fields and changes.is_paused != monitor.is_paused:
        if changes.is_paused:
            await reset_check_state(session, monitor, now, clear_last_result=False)
            monitor.is_paused = True
        else:
            monitor.is_paused = False
            monitor.next_check_at = now  # resume = check immediately
