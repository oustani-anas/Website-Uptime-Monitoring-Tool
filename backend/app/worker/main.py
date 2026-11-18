"""Worker process entry point: `python -m app.worker`.

  - waits for the database to be reachable,
  - every WORKER_POLL_SECONDS: `worker.tick()` (claim due monitors, start checks),
    then touches a heartbeat file (Docker healthcheck),
  - on SIGTERM/SIGINT: stops claiming, lets in-flight checks finish, exits.

The scheduling logic itself lives in `scheduler.Worker`.
"""

import asyncio
import logging
import signal
from pathlib import Path
from typing import Protocol

from sqlalchemy import text

from app.config import configure_logging, get_settings
from app.db import SessionLocal, engine
from app.worker.checker import build_http_client
from app.worker.scheduler import Worker

logger = logging.getLogger("app.worker")

SHUTDOWN_GRACE_EXTRA_SECONDS = 5  # on top of the check timeout; < compose stop_grace_period


class Tickable(Protocol):
    async def tick(self) -> None: ...
    async def shutdown(self, grace_seconds: float) -> None: ...


async def wait_for_db(stop: asyncio.Event, retry_seconds: float = 2) -> None:
    """Block until a trivial query succeeds (or we're asked to stop)."""
    while not stop.is_set():
        try:
            async with engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
            return
        except Exception as exc:  # noqa: BLE001 - any failure means "not ready yet"
            logger.warning("Database not ready (%s), retrying in %ss", exc.__class__.__name__, retry_seconds)
            await _sleep_or_stop(stop, retry_seconds)


def touch_heartbeat(path: str) -> None:
    Path(path).touch()


async def run(stop: asyncio.Event, worker: Tickable | None = None) -> None:
    settings = get_settings()
    await wait_for_db(stop)
    if stop.is_set():
        return

    client = build_http_client(timeout=settings.check_timeout_seconds, max_connections=settings.worker_concurrency)
    worker = worker or Worker(settings, SessionLocal, client)
    logger.info(
        "Worker started (poll %ss, concurrency %d, timeout %ss)",
        settings.worker_poll_seconds, settings.worker_concurrency, settings.check_timeout_seconds,
    )
    try:
        while not stop.is_set():
            try:
                await worker.tick()
            except Exception:
                # Never let one bad iteration kill the worker; log and keep going.
                logger.exception("Worker tick failed")
            touch_heartbeat(settings.worker_heartbeat_file)
            await _sleep_or_stop(stop, settings.worker_poll_seconds)
    finally:
        await worker.shutdown(settings.check_timeout_seconds + SHUTDOWN_GRACE_EXTRA_SECONDS)
        await client.aclose()
        logger.info("Worker stopped")


async def _sleep_or_stop(stop: asyncio.Event, seconds: float) -> None:
    """Sleep, but wake immediately when a shutdown is requested."""
    try:
        await asyncio.wait_for(stop.wait(), timeout=seconds)
    except TimeoutError:
        pass


async def _main() -> None:
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stop.set)
    try:
        await run(stop)
    finally:
        await engine.dispose()


def main() -> None:
    configure_logging()
    asyncio.run(_main())
