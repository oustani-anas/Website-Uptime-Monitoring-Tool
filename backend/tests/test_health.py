from collections.abc import AsyncIterator

from httpx import ASGITransport, AsyncClient

from app.db import get_session
from app.main import app


async def test_health_ok(client: AsyncClient) -> None:
    resp = await client.get("/api/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok", "db": "ok"}


async def test_health_returns_503_when_db_unreachable() -> None:
    class BrokenSession:
        async def execute(self, *args, **kwargs):
            raise ConnectionRefusedError("db down")

    async def _broken() -> AsyncIterator[BrokenSession]:
        yield BrokenSession()

    app.dependency_overrides[get_session] = _broken
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.get("/api/health")
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 503
    assert resp.json() == {"status": "error", "db": "error"}
