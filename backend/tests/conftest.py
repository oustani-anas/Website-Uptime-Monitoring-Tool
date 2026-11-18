"""Shared test fixtures.

Database strategy (SPEC §10):
  - Tests use a separate database (TEST_DATABASE_URL -> `uptime_test`).
  - The schema is created once per test session from the ORM models.
  - Each test runs inside an outer transaction that is rolled back afterwards,
    so tests are isolated and leave no data behind. Code under test may call
    `session.commit()`; with `join_transaction_mode="create_savepoint"` that only
    commits a SAVEPOINT inside the outer transaction.
"""

from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine

from app.config import get_settings
from app.db import get_session
from app.main import app
from app.models import Base


@pytest_asyncio.fixture(scope="session")
async def engine() -> AsyncIterator[AsyncEngine]:
    settings = get_settings()
    url = settings.test_database_url
    if not url:
        pytest.exit("TEST_DATABASE_URL is not set", returncode=1)
    if url == settings.database_url:
        # Guard: the fixture drops all tables, never point it at real data.
        pytest.exit("TEST_DATABASE_URL must differ from DATABASE_URL", returncode=1)

    eng = create_async_engine(url)
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield eng
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await eng.dispose()


@pytest_asyncio.fixture
async def session(engine: AsyncEngine) -> AsyncIterator[AsyncSession]:
    async with engine.connect() as conn:
        outer = await conn.begin()
        s = AsyncSession(bind=conn, expire_on_commit=False, join_transaction_mode="create_savepoint")
        try:
            yield s
        finally:
            await s.close()
            await outer.rollback()


@pytest.fixture
def fake_dns(monkeypatch: pytest.MonkeyPatch) -> dict[str, list[str]]:
    """Replace real DNS with a dict: {hostname: [ip, ...]}.

    Unknown hosts resolve to a public documentation-range address by default,
    so tests never depend on the network. Map a host to [] to simulate NXDOMAIN.
    """
    import ipaddress

    from app.services import url_safety

    records: dict[str, list[str]] = {}

    async def _resolve(host: str, port: int | None) -> list:
        ips = records.get(host, ["93.184.216.34"])
        if not ips:
            raise url_safety.HostResolutionError(f"Could not resolve host {host!r}")
        return [ipaddress.ip_address(ip) for ip in ips]

    monkeypatch.setattr(url_safety, "resolve_host", _resolve)
    return records


@pytest_asyncio.fixture
async def client(session: AsyncSession) -> AsyncIterator[AsyncClient]:
    """HTTP client calling the FastAPI app in-process, bound to the test session."""

    async def _override_session() -> AsyncIterator[AsyncSession]:
        yield session

    app.dependency_overrides[get_session] = _override_session
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()
