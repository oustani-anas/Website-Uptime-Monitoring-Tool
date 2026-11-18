"""The Worker: claims due monitors and runs their checks concurrently.

Concurrency model (SPEC §6, liveness requirement):
  - Every check runs as its own asyncio task and records its own result when done.
  - `tick()` claims only as many monitors as there are free slots
    (WORKER_CONCURRENCY - checks in flight), then returns immediately.
  This bounds concurrency exactly like a semaphore would, but never leases monitors
  that would just sit waiting for a slot, and the main loop (and its heartbeat)
  never blocks on slow checks.
"""

import asyncio
import logging
import time
from collections.abc import Callable, Coroutine
from typing import Any

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.worker import checker, retention, store
from app.worker.state import Event

logger = logging.getLogger(__name__)

RETENTION_EVERY_SECONDS = 3600

SessionFactory = Callable[[], AsyncSession]


class Worker:
    def __init__(self, settings: Settings, session_factory: SessionFactory, client: httpx.AsyncClient) -> None:
        self.settings = settings
        self.session_factory = session_factory
        self.client = client
        self._in_flight: set[asyncio.Task] = set()
        self._retention_task: asyncio.Task | None = None
        self._last_retention: float | None = None

    @property
    def in_flight(self) -> int:
        return len(self._in_flight)

    async def tick(self) -> None:
        """One scheduling iteration. Returns quickly; checks continue in the background."""
        self._maybe_start_retention()

        free_slots = self.settings.worker_concurrency - len(self._in_flight)
        if free_slots <= 0:
            return
        async with self.session_factory() as session:
            claimed = await store.claim_due(session, min(free_slots, self.settings.worker_batch_size))
        for monitor in claimed:
            self._spawn(self._check_and_record(monitor))
        if claimed:
            logger.debug("Claimed %d monitor(s), %d check(s) in flight", len(claimed), len(self._in_flight))

    async def _check_and_record(self, monitor: store.ClaimedMonitor) -> None:
        try:
            result = await checker.perform_check(
                self.client,
                monitor.url,
                timeout=self.settings.check_timeout_seconds,
                max_redirects=self.settings.max_redirects,
            )
            async with self.session_factory() as session:
                event = await store.record_result(
                    session,
                    monitor,
                    result,
                    failure_threshold=self.settings.failure_threshold,
                    retry_interval_seconds=self.settings.retry_interval_seconds,
                )
        except Exception:
            # Unexpected (e.g. DB down). The lease keeps the monitor from being retried
            # in a tight loop; it will simply be checked again after its interval.
            logger.exception("Check of monitor %s failed unexpectedly", monitor.id)
            return

        logger.debug(
            "Monitor %s %s: up=%s status=%s %sms %s",
            monitor.id, monitor.url, result.is_up, result.status_code,
            result.response_time_ms, result.error_type or "",
        )
        if event == Event.DOWN:
            logger.warning("Monitor %s is DOWN: %s (%s)", monitor.id, monitor.url, result.error_message)
        elif event == Event.RECOVERED:
            logger.info("Monitor %s RECOVERED: %s", monitor.id, monitor.url)

    def _maybe_start_retention(self) -> None:
        """Run retention at startup, then hourly, as a background task (never overlapping)."""
        if self._retention_task is not None and not self._retention_task.done():
            return
        now = time.monotonic()
        if self._last_retention is not None and now - self._last_retention < RETENTION_EVERY_SECONDS:
            return
        self._last_retention = now
        # Tracked separately from _in_flight: retention must never take a check slot.
        self._retention_task = asyncio.create_task(self._run_retention())

    async def _run_retention(self) -> None:
        try:
            async with self.session_factory() as session:
                deleted = await retention.purge_old_checks(session, self.settings.retention_days)
            logger.info("Retention: deleted %d check(s) older than %d days", deleted, self.settings.retention_days)
        except Exception:
            logger.exception("Retention job failed")

    def _spawn(self, coro: Coroutine[Any, Any, None]) -> asyncio.Task:
        task = asyncio.create_task(coro)
        self._in_flight.add(task)
        task.add_done_callback(self._in_flight.discard)
        return task

    async def shutdown(self, grace_seconds: float) -> None:
        """Let in-flight checks (and retention) finish up to `grace_seconds`, then cancel the rest."""
        tasks = set(self._in_flight)
        if self._retention_task is not None and not self._retention_task.done():
            tasks.add(self._retention_task)
        if not tasks:
            return
        logger.info("Waiting for %d in-flight task(s) to finish", len(tasks))
        _, pending = await asyncio.wait(tasks, timeout=grace_seconds)
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)
