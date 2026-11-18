"""Worker scheduling (app/worker/scheduler.py): concurrency and liveness.

DB and HTTP are replaced with fakes; this tests only the orchestration.
"""

import asyncio
import contextlib
from datetime import UTC, datetime

import pytest

from app.config import Settings
from app.worker import scheduler
from app.worker.checker import CheckResult
from app.worker.scheduler import Worker
from app.worker.store import ClaimedMonitor


@contextlib.asynccontextmanager
async def fake_session():
    yield object()


@pytest.fixture
def harness(monkeypatch):
    """A Worker with fake claim/check/record. `release` lets the slow checks finish."""
    release = asyncio.Event()
    state = {"next_id": 0, "limits": [], "recorded": []}

    async def claim_due(session, limit):
        state["limits"].append(limit)
        claimed = [ClaimedMonitor(state["next_id"] + i, "https://x.example", 60) for i in range(limit)]
        state["next_id"] += limit
        return claimed

    async def perform_check(client, url, **kwargs):
        await release.wait()  # simulates a slow site
        return CheckResult(datetime.now(UTC), is_up=True, status_code=200)

    async def record_result(session, monitor, result, **kwargs):
        state["recorded"].append(monitor.id)

    async def no_retention(*args, **kwargs):
        return 0

    monkeypatch.setattr(scheduler.store, "claim_due", claim_due)
    monkeypatch.setattr(scheduler.checker, "perform_check", perform_check)
    monkeypatch.setattr(scheduler.store, "record_result", record_result)
    monkeypatch.setattr(scheduler.retention, "purge_old_checks", no_retention)

    settings = Settings(database_url="postgresql+asyncpg://unused", worker_concurrency=5, worker_batch_size=100)
    worker = Worker(settings, fake_session, client=None)
    return worker, release, state


async def test_tick_returns_immediately_while_checks_are_slow(harness) -> None:
    worker, release, _ = harness
    await asyncio.wait_for(worker.tick(), timeout=0.5)  # must not wait for the checks
    assert worker.in_flight == 5  # all slots used by checks; retention doesn't take one
    release.set()
    await worker.shutdown(grace_seconds=1)


async def test_claims_only_free_slots(harness) -> None:
    worker, release, state = harness
    await worker.tick()  # fills all 5 slots
    await worker.tick()  # no free slots -> doesn't claim at all
    assert state["limits"] == [5]

    release.set()
    await asyncio.sleep(0.05)  # let the checks finish and record
    assert sorted(state["recorded"]) == [0, 1, 2, 3, 4]

    await worker.tick()  # slots free again
    assert state["limits"] == [5, 5]
    await worker.shutdown(grace_seconds=1)


async def test_shutdown_waits_for_in_flight_checks(harness) -> None:
    worker, release, state = harness
    await worker.tick()
    asyncio.get_running_loop().call_later(0.05, release.set)  # checks finish shortly after shutdown starts
    await worker.shutdown(grace_seconds=2)
    assert len(state["recorded"]) == 5  # all results were recorded, not lost
    assert worker.in_flight == 0


async def test_shutdown_cancels_checks_that_exceed_grace(harness) -> None:
    worker, _, state = harness  # never released
    await worker.tick()
    await worker.shutdown(grace_seconds=0.05)
    assert state["recorded"] == []
    assert worker.in_flight == 0


async def test_retention_runs_at_start_then_not_again_within_the_hour(harness, monkeypatch) -> None:
    worker, release, _ = harness
    calls = 0

    async def counting_purge(*args, **kwargs):
        nonlocal calls
        calls += 1
        return 0

    monkeypatch.setattr(scheduler.retention, "purge_old_checks", counting_purge)
    release.set()
    for _ in range(3):
        await worker.tick()
        await asyncio.sleep(0.01)
    assert calls == 1
    await worker.shutdown(grace_seconds=1)
