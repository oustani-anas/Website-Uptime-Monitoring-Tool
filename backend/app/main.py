from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api import health, monitors
from app.config import configure_logging
from app.db import engine


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    # Startup
    configure_logging()
    yield
    # Shutdown: close pooled DB connections cleanly
    await engine.dispose()


app = FastAPI(
    title="Uptime Monitor API",
    version="0.1.0",
    description="Monitors website availability. See SPEC.md for the full contract.",
    lifespan=lifespan,
)

app.include_router(health.router, prefix="/api")
app.include_router(monitors.router, prefix="/api")
