from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Check, Incident, Monitor
from app.worker.retention import purge_old_checks

NOW = datetime(2026, 11, 18, 12, 0, tzinfo=UTC)


async def test_deletes_only_checks_older_than_retention_in_batches(session: AsyncSession) -> None:
    m = Monitor(name="m", url="https://example.com", interval_seconds=60)
    session.add(m)
    await session.flush()

    old = [NOW - timedelta(days=31, minutes=i) for i in range(5)]
    recent = [NOW - timedelta(days=29), NOW - timedelta(minutes=1)]
    session.add_all(Check(monitor_id=m.id, checked_at=t, is_up=True) for t in old + recent)
    session.add(Incident(monitor_id=m.id, started_at=NOW - timedelta(days=60), resolved_at=NOW - timedelta(days=59)))
    await session.commit()

    deleted = await purge_old_checks(session, retention_days=30, now=NOW, batch_size=2)  # forces 3 batches

    assert deleted == 5
    remaining = (await session.execute(select(Check.checked_at).where(Check.monitor_id == m.id))).scalars().all()
    assert sorted(remaining) == sorted(recent)
    # incidents are history and are never purged
    assert await session.scalar(select(func.count()).select_from(Incident).where(Incident.monitor_id == m.id)) == 1


async def test_nothing_to_delete(session: AsyncSession) -> None:
    assert await purge_old_checks(session, retention_days=30, now=NOW) == 0
