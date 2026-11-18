import pytest
from pydantic import ValidationError

from app.config import Settings


@pytest.mark.parametrize(
    "env",
    [
        {"WORKER_CONCURRENCY": "0"},
        {"CHECK_TIMEOUT_SECONDS": "-1"},
        {"FAILURE_THRESHOLD": "0"},
        {"RETENTION_DAYS": "0"},
        {"LOG_LEVEL": "VERBOSE"},
    ],
)
def test_invalid_settings_fail_fast(monkeypatch, env) -> None:
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    with pytest.raises(ValidationError):
        Settings()


def test_defaults_match_spec(monkeypatch) -> None:
    for key in ("CHECK_TIMEOUT_SECONDS", "FAILURE_THRESHOLD", "RETRY_INTERVAL_SECONDS", "RETENTION_DAYS"):
        monkeypatch.delenv(key, raising=False)
    s = Settings()
    assert (s.check_timeout_seconds, s.failure_threshold, s.retry_interval_seconds, s.retention_days) == (10, 3, 30, 30)
