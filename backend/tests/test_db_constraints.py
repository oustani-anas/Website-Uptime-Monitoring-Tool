"""The database itself enforces the core invariants, even if application code is buggy."""

from datetime import UTC, datetime

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Incident, Monitor


async def _monitor(session: AsyncSession) -> Monitor:
    m = Monitor(name="m", url="https://example.com", interval_seconds=60)
    session.add(m)
    await session.flush()
    return m


async def test_interval_check_constraint(session: AsyncSession) -> None:
    with pytest.raises(IntegrityError, match="ck_monitors_interval_allowed"):
        async with session.begin_nested():
            session.add(Monitor(name="m", url="https://example.com", interval_seconds=45))


async def test_only_one_open_incident_per_monitor(session: AsyncSession) -> None:
    m = await _monitor(session)
    session.add(Incident(monitor_id=m.id, started_at=datetime.now(UTC)))
    await session.flush()
    with pytest.raises(IntegrityError, match="uq_incidents_one_open_per_monitor"):
        async with session.begin_nested():
            session.add(Incident(monitor_id=m.id, started_at=datetime.now(UTC)))


async def test_many_resolved_incidents_are_allowed(session: AsyncSession) -> None:
    m = await _monitor(session)
    now = datetime.now(UTC)
    session.add_all(
        [
            Incident(monitor_id=m.id, started_at=now, resolved_at=now),
            Incident(monitor_id=m.id, started_at=now, resolved_at=now),
            Incident(monitor_id=m.id, started_at=now),  # plus one open
        ]
    )
    await session.flush()
