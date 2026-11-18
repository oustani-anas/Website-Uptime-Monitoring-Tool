"""Demo data (DECISIONS D10): `python -m app.seed`, run by the API entrypoint.

Only seeds when SEED_DEMO=true and the monitors table is empty, so it never
duplicates data or touches a database someone is already using.
"""

import asyncio
import logging

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import configure_logging, get_settings
from app.db import SessionLocal, engine
from app.models import Monitor

logger = logging.getLogger("app.seed")

# (name, url, interval_seconds). Two healthy sites and two that always fail.
DEMO_MONITORS: list[tuple[str, str, int]] = [
    ("Example", "https://example.com", 60),
    ("GitHub", "https://github.com", 300),
    ("HTTP 503 demo", "https://httpbin.org/status/503", 60),
    # .invalid is a reserved TLD (RFC 2606) and never resolves -> always a DNS failure
    ("DNS failure demo", "https://this-site-does-not-exist.invalid", 30),
]


async def seed_demo_monitors(session: AsyncSession) -> int:
    """Insert the demo monitors if there are none yet. Returns how many were added."""
    if await session.scalar(select(func.count()).select_from(Monitor)):
        return 0
    session.add_all(Monitor(name=n, url=u, interval_seconds=i) for n, u, i in DEMO_MONITORS)
    await session.commit()
    return len(DEMO_MONITORS)


async def _main() -> None:
    if not get_settings().seed_demo:
        logger.info("SEED_DEMO is off, skipping demo data")
        return
    try:
        async with SessionLocal() as session:
            added = await seed_demo_monitors(session)
    finally:
        await engine.dispose()
    if added:
        logger.info("Seeded %d demo monitors", added)
    else:
        logger.info("Monitors already exist, skipping demo data")


if __name__ == "__main__":
    configure_logging()
    asyncio.run(_main())
