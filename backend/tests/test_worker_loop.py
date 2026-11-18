"""Worker process loop (app/worker/main.py): heartbeat, error resilience, shutdown."""

import asyncio

import pytest

from app.config import get_settings
from app.worker import main as worker_main


class FakeWorker:
    def __init__(self, fail: bool = False) -> None:
        self.ticks = 0
        self.fail = fail
        self.shutdown_called = False

    async def tick(self) -> None:
        self.ticks += 1
        if self.fail:
            raise RuntimeError("boom")

    async def shutdown(self, grace_seconds: float) -> None:
        self.shutdown_called = True


@pytest.fixture
def fast_loop(tmp_path, monkeypatch):
    settings = get_settings()
    heartbeat = tmp_path / "heartbeat"
    monkeypatch.setattr(settings, "worker_heartbeat_file", str(heartbeat))
    monkeypatch.setattr(settings, "worker_poll_seconds", 0.01)

    async def db_ready(stop):  # skip the real DB wait
        return None

    monkeypatch.setattr(worker_main, "wait_for_db", db_ready)
    return heartbeat


async def test_writes_heartbeat_and_stops_on_signal(fast_loop) -> None:
    fake = FakeWorker()
    stop = asyncio.Event()
    task = asyncio.create_task(worker_main.run(stop, worker=fake))
    await asyncio.sleep(0.1)
    assert fast_loop.exists()
    assert fake.ticks > 1

    stop.set()  # what the SIGTERM handler does
    await asyncio.wait_for(task, timeout=1)  # exits promptly
    assert fake.shutdown_called  # in-flight checks get a chance to finish


async def test_survives_a_failing_tick(fast_loop) -> None:
    fake = FakeWorker(fail=True)
    stop = asyncio.Event()
    task = asyncio.create_task(worker_main.run(stop, worker=fake))
    await asyncio.sleep(0.1)
    stop.set()
    await asyncio.wait_for(task, timeout=1)
    assert fake.ticks > 1  # kept looping after exceptions
    assert fast_loop.exists()  # heartbeat still written
