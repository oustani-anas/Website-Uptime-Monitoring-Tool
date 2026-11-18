import logging

from fastapi import APIRouter, Depends, Response
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session

logger = logging.getLogger(__name__)

router = APIRouter(tags=["health"])


@router.get("/health")
async def health(response: Response, session: AsyncSession = Depends(get_session)) -> dict:
    """Liveness + DB round-trip. Used by the Docker healthcheck.

    Returns 503 when the database is unreachable, so Docker (and the worker's
    `depends_on: service_healthy`) can see that the API is not actually usable.
    """
    try:
        await session.execute(text("SELECT 1"))
    except Exception:
        logger.exception("Health check: database unreachable")
        response.status_code = 503
        return {"status": "error", "db": "error"}
    return {"status": "ok", "db": "ok"}
