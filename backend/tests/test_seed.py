from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Monitor
from app.seed import DEMO_MONITORS, seed_demo_monitors


async def test_seeds_when_empty_and_never_twice(session: AsyncSession) -> None:
    assert await seed_demo_monitors(session) == len(DEMO_MONITORS)
    assert await seed_demo_monitors(session) == 0
    assert await session.scalar(select(func.count()).select_from(Monitor)) == len(DEMO_MONITORS)


async def test_does_not_seed_into_existing_data(session: AsyncSession) -> None:
    session.add(Monitor(name="mine", url="https://example.com", interval_seconds=60))
    await session.commit()
    assert await seed_demo_monitors(session) == 0
