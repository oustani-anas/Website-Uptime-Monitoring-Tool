"""The up/down state machine (SPEC §6, "State transitions"). Pure: no I/O.

    PENDING/UP --fail x1..threshold-1--> same status, "failing" (fast re-checks)
    PENDING/UP --fail x threshold------> DOWN   (open incident, event "down")
    DOWN       --fail-----------------> DOWN   (normal interval)
    any        --success--------------> UP     (if it was DOWN: close incident, event "recovered")
"""

import enum
from dataclasses import dataclass
from datetime import datetime, timedelta

from app.models import MonitorStatus
from app.worker.checker import CheckResult


class Event(enum.StrEnum):
    """Notable transitions, reported to the caller (logged now, webhook in Stage 8)."""

    DOWN = "down"
    RECOVERED = "recovered"


@dataclass(frozen=True)
class MonitorState:
    status: MonitorStatus
    consecutive_failures: int
    failing_since: datetime | None


@dataclass(frozen=True)
class Transition:
    state: MonitorState
    next_check_at: datetime
    open_incident: bool = False
    close_incident: bool = False
    event: Event | None = None


def apply_result(
    state: MonitorState,
    result: CheckResult,
    *,
    interval_seconds: int,
    failure_threshold: int,
    retry_interval_seconds: int,
) -> Transition:
    now = result.checked_at
    normal_next = now + timedelta(seconds=interval_seconds)

    if result.is_up:
        was_down = state.status == MonitorStatus.DOWN
        return Transition(
            state=MonitorState(MonitorStatus.UP, consecutive_failures=0, failing_since=None),
            next_check_at=normal_next,
            close_incident=was_down,
            event=Event.RECOVERED if was_down else None,
        )

    failures = state.consecutive_failures + 1
    # The incident starts at the *first* failure of the streak, not at confirmation.
    failing_since = state.failing_since or now

    if state.status != MonitorStatus.DOWN and failures >= failure_threshold:
        return Transition(
            state=MonitorState(MonitorStatus.DOWN, failures, failing_since),
            next_check_at=normal_next,
            open_incident=True,
            event=Event.DOWN,
        )

    if state.status == MonitorStatus.DOWN:
        # Already confirmed down: back to the normal interval (predictable load, D4).
        next_check_at = normal_next
    else:
        # Not yet confirmed: re-check quickly to confirm or clear the failure.
        next_check_at = now + timedelta(seconds=min(interval_seconds, retry_interval_seconds))

    return Transition(
        state=MonitorState(state.status, failures, failing_since),
        next_check_at=next_check_at,
    )
