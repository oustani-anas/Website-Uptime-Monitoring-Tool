"""Database engine and session handling (SQLAlchemy 2.0 async).

`create_async_engine` does not connect until first use, so importing this
module is cheap and safe even if the database is not up yet.
"""

from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import get_settings

engine = create_async_engine(
    get_settings().database_url,
    pool_pre_ping=True,  # transparently replace connections dropped by a DB restart
    # Fail fast if Postgres hangs (asyncpg default is 60s, longer than any healthcheck).
    connect_args={"timeout": 5},
)

SessionLocal = async_sessionmaker(engine, expire_on_commit=False)


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency: one session per request. Tests override this."""
    async with SessionLocal() as session:
        yield session
