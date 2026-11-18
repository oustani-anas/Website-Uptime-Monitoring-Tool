"""Data retention (SPEC §6, DECISIONS D7): delete checks older than RETENTION_DAYS.

Incidents are never deleted; they are the long-term history.
"""

from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Check


async def purge_old_checks(
    session: AsyncSession,
    retention_days: int,
    *,
    now: datetime | None = None,
    batch_size: int = 5000,
) -> int:
    """Delete old checks in batches; returns how many rows were removed.

    Batches keep each transaction (and its locks) short, so a large first purge
    never blocks the worker writing new checks for long.
    """
    cutoff = (now or datetime.now(UTC)) - timedelta(days=retention_days)
    total = 0
    while True:
        batch = select(Check.id).where(Check.checked_at < cutoff).limit(batch_size)
        result = await session.execute(
            delete(Check).where(Check.id.in_(batch)).execution_options(synchronize_session=False)
        )
        await session.commit()
        total += result.rowcount
        if result.rowcount < batch_size:
            return total
