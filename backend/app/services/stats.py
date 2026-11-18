"""Availability statistics, computed in SQL at query time (SPEC §6 "Uptime", DECISIONS D8).

uptime % = up checks / all checks in the window. `None` when there are no checks.
Average response time only uses successful checks: timeouts have no time at all,
and error pages are often much faster or slower than the real page.
"""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal

from sqlalchemy import and_, func, literal, literal_column, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Check, Incident

WINDOW_24H = timedelta(hours=24)
WINDOW_7D = timedelta(days=7)

ChartRange = Literal["24h", "7d"]
# range -> (window, bucket size in seconds): 24h = 288 x 5 min, 7d = 168 x 1 h
CHART_RANGES: dict[str, tuple[timedelta, int]] = {
    "24h": (WINDOW_24H, 300),
    "7d": (WINDOW_7D, 3600),
}
# Fixed origin so bucket boundaries are stable (aligned to whole 5-min / 1-h UTC marks).
BUCKET_ORIGIN = datetime(2000, 1, 1, tzinfo=UTC)


def _percent(up: int, total: int) -> float | None:
    return round(100 * up / total, 2) if total else None


@dataclass(frozen=True)
class MonitorStatsRow:
    uptime_24h: float | None
    uptime_7d: float | None
    avg_response_ms_24h: int | None


async def uptime_24h_by_monitor(session: AsyncSession, now: datetime | None = None) -> dict[int, float]:
    """uptime_24h for every monitor that has checks, in ONE grouped query (dashboard)."""
    since = (now or datetime.now(UTC)) - WINDOW_24H
    rows = await session.execute(
        select(Check.monitor_id, func.count(), func.count().filter(Check.is_up))
        .where(Check.checked_at >= since)
        .group_by(Check.monitor_id)
    )
    return {monitor_id: _percent(up, total) for monitor_id, total, up in rows}


async def monitor_stats(session: AsyncSession, monitor_id: int, now: datetime | None = None) -> MonitorStatsRow:
    """24h + 7d uptime and 24h average response time for one monitor, in ONE query."""
    now = now or datetime.now(UTC)
    in_24h = Check.checked_at >= now - WINDOW_24H
    row = (
        await session.execute(
            select(
                func.count().filter(in_24h),
                func.count().filter(and_(in_24h, Check.is_up)),
                func.count(),
                func.count().filter(Check.is_up),
                func.avg(Check.response_time_ms).filter(and_(in_24h, Check.is_up)),
            ).where(Check.monitor_id == monitor_id, Check.checked_at >= now - WINDOW_7D)
        )
    ).one()
    total_24h, up_24h, total_7d, up_7d, avg_ms = row
    return MonitorStatsRow(
        uptime_24h=_percent(up_24h, total_24h),
        uptime_7d=_percent(up_7d, total_7d),
        avg_response_ms_24h=round(avg_ms) if avg_ms is not None else None,
    )


@dataclass(frozen=True)
class ResponseTimeBucket:
    t: datetime
    avg_ms: int | None  # None if every check in the bucket failed
    max_ms: int | None
    checks: int
    failures: int


async def response_time_buckets(
    session: AsyncSession, monitor_id: int, range_: ChartRange, now: datetime | None = None
) -> tuple[int, list[ResponseTimeBucket]]:
    """Checks grouped into fixed time buckets for the chart. Returns (bucket_seconds, points).

    Buckets without any checks are omitted (no data is not the same as 0 ms).
    """
    window, bucket_seconds = CHART_RANGES[range_]
    since = (now or datetime.now(UTC)) - window
    # bucket_seconds comes from the fixed table above, never from user input.
    stride = literal_column(f"interval '{bucket_seconds} seconds'")
    bucket = func.date_bin(stride, Check.checked_at, literal(BUCKET_ORIGIN)).label("t")

    rows = await session.execute(
        select(
            bucket,
            func.avg(Check.response_time_ms).filter(Check.is_up),
            func.max(Check.response_time_ms).filter(Check.is_up),
            func.count(),
            func.count().filter(~Check.is_up),
        )
        .where(Check.monitor_id == monitor_id, Check.checked_at >= since)
        .group_by(bucket)
        .order_by(bucket)
    )
    points = [
        ResponseTimeBucket(
            t=t,
            avg_ms=round(avg) if avg is not None else None,
            max_ms=mx,
            checks=checks,
            failures=failures,
        )
        for t, avg, mx, checks, failures in rows
    ]
    return bucket_seconds, points


async def recent_checks(
    session: AsyncSession, monitor_id: int, *, limit: int, before: datetime | None = None
) -> list[Check]:
    """Newest first. `before` pages backwards: pass the oldest `checked_at` you have."""
    query = select(Check).where(Check.monitor_id == monitor_id)
    if before is not None:
        query = query.where(Check.checked_at < before)
    result = await session.execute(query.order_by(Check.checked_at.desc(), Check.id.desc()).limit(limit))
    return list(result.scalars())


async def incident_history(session: AsyncSession, monitor_id: int, *, limit: int) -> list[Incident]:
    result = await session.execute(
        select(Incident)
        .where(Incident.monitor_id == monitor_id)
        .order_by(Incident.started_at.desc(), Incident.id.desc())
        .limit(limit)
    )
    return list(result.scalars())
