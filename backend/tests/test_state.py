"""State machine (app/worker/state.py): pure functions, no DB, no network."""

from datetime import UTC, datetime, timedelta

from app.models import ErrorType, MonitorStatus
from app.worker.checker import CheckResult
from app.worker.state import Event, MonitorState, apply_result

T0 = datetime(2026, 11, 18, 12, 0, tzinfo=UTC)
FRESH = MonitorState(MonitorStatus.PENDING, 0, None)


def ok(at: datetime = T0) -> CheckResult:
    return CheckResult(at, is_up=True, status_code=200, response_time_ms=100)


def fail(at: datetime = T0) -> CheckResult:
    return CheckResult(at, is_up=False, error_type=ErrorType.TIMEOUT, error_message="timeout")


def step(state: MonitorState, result: CheckResult, interval: int = 300):
    return apply_result(state, result, interval_seconds=interval, failure_threshold=3, retry_interval_seconds=30)


def test_first_success_marks_up() -> None:
    t = step(FRESH, ok())
    assert t.state == MonitorState(MonitorStatus.UP, 0, None)
    assert t.next_check_at == T0 + timedelta(seconds=300)
    assert (t.open_incident, t.close_incident, t.event) == (False, False, None)


def test_one_and_two_failures_do_not_mark_down_and_retry_fast() -> None:
    up = MonitorState(MonitorStatus.UP, 0, None)
    t1 = step(up, fail(T0))
    assert t1.state == MonitorState(MonitorStatus.UP, 1, T0)
    assert t1.next_check_at == T0 + timedelta(seconds=30)  # fast re-check
    assert not t1.open_incident and t1.event is None

    t2 = step(t1.state, fail(T0 + timedelta(seconds=30)))
    assert t2.state == MonitorState(MonitorStatus.UP, 2, T0)  # failing_since stays at the first failure
    assert not t2.open_incident


def test_third_failure_marks_down_and_opens_incident_from_first_failure() -> None:
    state = MonitorState(MonitorStatus.UP, 2, T0)
    t = step(state, fail(T0 + timedelta(seconds=60)))
    assert t.state.status == MonitorStatus.DOWN
    assert t.state.failing_since == T0  # incident start = first failure, not confirmation
    assert t.open_incident and t.event == Event.DOWN
    assert t.next_check_at == T0 + timedelta(seconds=60 + 300)  # back to normal interval


def test_new_monitor_that_never_works_goes_pending_to_down() -> None:
    state = FRESH
    for i in range(3):
        t = step(state, fail(T0 + timedelta(seconds=30 * i)))
        state = t.state
    assert state.status == MonitorStatus.DOWN
    assert t.open_incident


def test_further_failures_while_down_do_not_reopen() -> None:
    down = MonitorState(MonitorStatus.DOWN, 3, T0)
    t = step(down, fail(T0 + timedelta(minutes=5)))
    assert t.state == MonitorState(MonitorStatus.DOWN, 4, T0)
    assert not t.open_incident and t.event is None
    assert t.next_check_at == T0 + timedelta(minutes=5, seconds=300)  # normal interval while down


def test_recovery_closes_incident() -> None:
    down = MonitorState(MonitorStatus.DOWN, 5, T0)
    t = step(down, ok(T0 + timedelta(minutes=10)))
    assert t.state == MonitorState(MonitorStatus.UP, 0, None)
    assert t.close_incident and t.event == Event.RECOVERED


def test_success_after_blip_clears_failures_without_incident() -> None:
    failing = MonitorState(MonitorStatus.UP, 2, T0)
    t = step(failing, ok())
    assert t.state == MonitorState(MonitorStatus.UP, 0, None)
    assert not t.close_incident and t.event is None


def test_retry_never_slower_than_the_interval() -> None:
    # A 30s monitor keeps its 30s cadence; min(interval, retry) never lengthens it.
    t = step(MonitorState(MonitorStatus.UP, 0, None), fail(), interval=30)
    assert t.next_check_at == T0 + timedelta(seconds=30)
