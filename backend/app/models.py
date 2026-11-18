"""ORM models (SPEC §5).

Integrity rules are enforced by the database itself, not only by Python:
  - allowed check intervals          -> CHECK constraint
  - deleting a monitor removes data  -> ON DELETE CASCADE foreign keys
  - at most one open incident        -> partial UNIQUE index

There are deliberately no ORM `relationship()`s: the DB handles cascades, and
explicit queries keep it obvious which SQL runs (no lazy-loading surprises in async code).
"""

import enum
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    MetaData,
    String,
    func,
    text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

ALLOWED_INTERVALS: tuple[int, ...] = (30, 60, 300, 900, 3600)

# Deterministic constraint/index names, so Alembic migrations are stable and reviewable.
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class MonitorStatus(enum.StrEnum):
    """Confirmed state of a monitor (see SPEC §6 for transitions)."""

    PENDING = "pending"  # no confirmed result yet (new, resumed, or URL changed)
    UP = "up"
    DOWN = "down"  # confirmed after FAILURE_THRESHOLD consecutive failures


class ErrorType(enum.StrEnum):
    """Why a check failed. Stored on checks, incidents and the monitor's last result."""

    TIMEOUT = "timeout"
    DNS = "dns"
    CONNECTION = "connection"
    SSL = "ssl"
    HTTP_4XX = "http_4xx"
    HTTP_5XX = "http_5xx"
    TOO_MANY_REDIRECTS = "too_many_redirects"
    BLOCKED_ADDRESS = "blocked_address"
    UNKNOWN = "unknown"


def _pg_enum(enum_cls: type[enum.Enum], name: str) -> Enum:
    # Store the lowercase *values* ("up"), not the member names ("UP").
    return Enum(enum_cls, name=name, values_callable=lambda e: [m.value for m in e])


monitor_status_enum = _pg_enum(MonitorStatus, "monitor_status")
error_type_enum = _pg_enum(ErrorType, "error_type")

TZDateTime = DateTime(timezone=True)  # always timestamptz, always UTC


class Monitor(Base):
    __tablename__ = "monitors"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    url: Mapped[str] = mapped_column(String(2048))
    interval_seconds: Mapped[int]
    is_paused: Mapped[bool] = mapped_column(default=False, server_default=text("false"))

    # Check state, maintained by the worker
    status: Mapped[MonitorStatus] = mapped_column(
        monitor_status_enum, default=MonitorStatus.PENDING, server_default=MonitorStatus.PENDING.value
    )
    consecutive_failures: Mapped[int] = mapped_column(default=0, server_default=text("0"))
    failing_since: Mapped[datetime | None] = mapped_column(TZDateTime)

    # Last result, denormalized so the dashboard needs a single query
    last_checked_at: Mapped[datetime | None] = mapped_column(TZDateTime)
    last_status_code: Mapped[int | None]
    last_response_time_ms: Mapped[int | None]
    last_error_type: Mapped[ErrorType | None] = mapped_column(error_type_enum)

    next_check_at: Mapped[datetime] = mapped_column(TZDateTime, server_default=func.now())
    created_at: Mapped[datetime] = mapped_column(TZDateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(TZDateTime, server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        CheckConstraint(
            f"interval_seconds IN ({', '.join(map(str, ALLOWED_INTERVALS))})",
            name="interval_allowed",
        ),
        # The worker's "what is due?" query only ever looks at active monitors.
        Index("ix_monitors_due", "next_check_at", postgresql_where=text("NOT is_paused")),
    )


class Check(Base):
    __tablename__ = "checks"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    monitor_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("monitors.id", ondelete="CASCADE"))
    checked_at: Mapped[datetime] = mapped_column(TZDateTime)
    is_up: Mapped[bool]
    status_code: Mapped[int | None]
    response_time_ms: Mapped[int | None]
    error_type: Mapped[ErrorType | None] = mapped_column(error_type_enum)
    error_message: Mapped[str | None] = mapped_column(String(500))

    __table_args__ = (
        # "Latest checks for monitor X" and per-monitor time windows (detail page, uptime %).
        # Postgres scans a B-tree backwards for ORDER BY ... DESC, so no DESC index is needed.
        Index("ix_checks_monitor_id_checked_at", "monitor_id", "checked_at"),
        # Retention job: DELETE ... WHERE checked_at < cutoff
        Index("ix_checks_checked_at", "checked_at"),
    )


class Incident(Base):
    __tablename__ = "incidents"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    monitor_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("monitors.id", ondelete="CASCADE"))
    started_at: Mapped[datetime] = mapped_column(TZDateTime)  # first failure of the streak
    resolved_at: Mapped[datetime | None] = mapped_column(TZDateTime)  # NULL = ongoing
    error_type: Mapped[ErrorType | None] = mapped_column(error_type_enum)
    error_message: Mapped[str | None] = mapped_column(String(500))

    __table_args__ = (
        Index("ix_incidents_monitor_id_started_at", "monitor_id", "started_at"),
        # Guarantees at most one *open* incident per monitor, even with concurrent writers.
        Index(
            "uq_incidents_one_open_per_monitor",
            "monitor_id",
            unique=True,
            postgresql_where=text("resolved_at IS NULL"),
        ),
    )
