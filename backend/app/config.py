"""Application settings, read from environment variables (see .env.example).

The API and the worker both import this module, so every tunable lives in one place.
"""

import logging
from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Invalid values (e.g. WORKER_CONCURRENCY=0) fail at startup, not at runtime."""

    model_config = SettingsConfigDict(extra="ignore")

    database_url: str
    test_database_url: str | None = None
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"

    # Worker / check behaviour
    check_timeout_seconds: float = Field(10, gt=0)
    worker_concurrency: int = Field(20, gt=0)
    worker_poll_seconds: float = Field(2, gt=0)
    worker_batch_size: int = Field(100, gt=0)
    worker_heartbeat_file: str = "/tmp/worker-heartbeat"
    failure_threshold: int = Field(3, ge=1)
    retry_interval_seconds: int = Field(30, gt=0)
    max_redirects: int = Field(5, ge=0)
    retention_days: int = Field(30, ge=1)

    # Demo data
    seed_demo: bool = True

    # Bonus: alert webhook
    webhook_url: str | None = None
    webhook_kind: Literal["slack", "discord"] = "discord"


@lru_cache
def get_settings() -> Settings:
    return Settings()


def configure_logging() -> None:
    logging.basicConfig(
        level=get_settings().log_level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    # httpx logs every request at INFO; the worker logs what matters (DOWN/RECOVERED) itself.
    logging.getLogger("httpx").setLevel(logging.WARNING)
