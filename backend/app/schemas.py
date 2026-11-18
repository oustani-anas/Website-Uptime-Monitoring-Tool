"""Request/response models for the API (SPEC §7)."""

from datetime import UTC, datetime
from typing import Annotated, Literal

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    computed_field,
    model_validator,
)
from pydantic_core import PydanticCustomError

from app.models import ErrorType, MonitorStatus
from app.services.url_safety import UnsafeURLError, validate_url_format

Interval = Literal[30, 60, 300, 900, 3600]  # mirrors models.ALLOWED_INTERVALS
DisplayStatus = Literal["pending", "up", "down", "failing", "paused"]

Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]


def _check_url_format(value: str) -> str:
    try:
        return validate_url_format(value)
    except UnsafeURLError as exc:
        # A custom error type keeps the message clean (no "Value error, " prefix).
        raise PydanticCustomError("invalid_url", str(exc)) from None


MonitorURL = Annotated[str, AfterValidator(_check_url_format)]


# ---------- requests ----------


class MonitorCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Name
    url: MonitorURL
    interval_seconds: Interval = 60


class MonitorUpdate(BaseModel):
    """Partial update: only the fields that are sent are changed."""

    model_config = ConfigDict(extra="forbid")

    name: Name | None = None
    url: MonitorURL | None = None
    interval_seconds: Interval | None = None
    is_paused: bool | None = None

    @model_validator(mode="after")
    def _no_explicit_nulls(self) -> "MonitorUpdate":
        # Omitting a field means "keep it"; sending null for it is a client error.
        for field in self.model_fields_set:
            if getattr(self, field) is None:
                raise PydanticCustomError("null_not_allowed", "{field} cannot be null", {"field": field})
        return self


# ---------- responses ----------


class IncidentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    started_at: datetime
    resolved_at: datetime | None
    error_type: ErrorType | None
    error_message: str | None

    @computed_field
    @property
    def duration_seconds(self) -> int:
        end = self.resolved_at or datetime.now(UTC)
        return max(0, int((end - self.started_at).total_seconds()))


class MonitorOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    url: str
    interval_seconds: int
    is_paused: bool
    status: MonitorStatus
    consecutive_failures: int
    last_checked_at: datetime | None
    last_status_code: int | None
    last_response_time_ms: int | None
    last_error_type: ErrorType | None
    next_check_at: datetime
    created_at: datetime
    uptime_24h: float | None = None  # filled in by the stats service (Stage 4)

    @computed_field
    @property
    def display_status(self) -> DisplayStatus:
        """What the UI shows. Derived, never stored (SPEC §5)."""
        if self.is_paused:
            return "paused"
        if self.status != MonitorStatus.DOWN and self.consecutive_failures > 0:
            return "failing"  # failing, but not yet confirmed DOWN
        return self.status.value


class MonitorStats(BaseModel):
    uptime_24h: float | None = None  # Stage 4
    uptime_7d: float | None = None  # Stage 4
    avg_response_ms_24h: int | None = None  # Stage 4
    open_incident: IncidentOut | None = None


class MonitorDetail(MonitorOut):
    stats: MonitorStats = Field(default_factory=MonitorStats)
