"""Monitor CRUD endpoints (SPEC §7)."""

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Response, status
from fastapi.exceptions import RequestValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.models import Monitor
from app.schemas import (
    CheckOut,
    IncidentOut,
    MonitorCreate,
    MonitorDetail,
    MonitorOut,
    MonitorStats,
    MonitorUpdate,
    ResponseTimePoint,
    ResponseTimes,
)
from app.services import monitors as monitor_service
from app.services import stats as stats_service
from app.services.url_safety import UnsafeURLError, validate_monitor_url

router = APIRouter(prefix="/monitors", tags=["monitors"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]
MonitorId = Annotated[int, Path(gt=0)]


async def _get_monitor_or_404(session: AsyncSession, monitor_id: int) -> Monitor:
    monitor = await session.get(Monitor, monitor_id)
    if monitor is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Monitor not found")
    return monitor


async def _validate_url_or_422(url: str) -> str:
    """DNS-based SSRF check. It's async, so it can't run inside the Pydantic model.

    Raises the same 422 shape as Pydantic's own validation errors, so the client
    handles every URL problem the same way.
    """
    try:
        return await validate_monitor_url(url)
    except UnsafeURLError as exc:
        raise RequestValidationError(
            [{"type": "invalid_url", "loc": ("body", "url"), "msg": str(exc), "input": url}]
        ) from None


@router.get("", response_model=list[MonitorOut])
async def list_monitors(session: SessionDep) -> list[MonitorOut]:
    result = await session.execute(select(Monitor).order_by(Monitor.id))
    uptime = await stats_service.uptime_24h_by_monitor(session)  # one query for all monitors
    return [
        MonitorOut.model_validate(m).model_copy(update={"uptime_24h": uptime.get(m.id)})
        for m in result.scalars()
    ]


@router.post("", response_model=MonitorOut, status_code=status.HTTP_201_CREATED)
async def create_monitor(payload: MonitorCreate, session: SessionDep) -> Monitor:
    url = await _validate_url_or_422(payload.url)
    monitor = Monitor(name=payload.name, url=url, interval_seconds=payload.interval_seconds)
    session.add(monitor)
    await session.commit()
    await session.refresh(monitor)  # load DB-generated values (id, timestamps, next_check_at)
    return monitor


@router.get("/{monitor_id}", response_model=MonitorDetail)
async def get_monitor(monitor_id: MonitorId, session: SessionDep) -> MonitorDetail:
    monitor = await _get_monitor_or_404(session, monitor_id)
    incident = await monitor_service.get_open_incident(session, monitor.id)
    numbers = await stats_service.monitor_stats(session, monitor.id)
    detail = MonitorDetail.model_validate(monitor)
    detail.uptime_24h = numbers.uptime_24h
    detail.stats = MonitorStats(
        uptime_24h=numbers.uptime_24h,
        uptime_7d=numbers.uptime_7d,
        avg_response_ms_24h=numbers.avg_response_ms_24h,
        open_incident=IncidentOut.model_validate(incident) if incident else None,
    )
    return detail


@router.get("/{monitor_id}/checks", response_model=list[CheckOut])
async def list_checks(
    monitor_id: MonitorId,
    session: SessionDep,
    limit: Annotated[int, Query(ge=1, le=500)] = 50,
    before: Annotated[datetime | None, Query(description="Only checks older than this (for paging)")] = None,
) -> list:
    await _get_monitor_or_404(session, monitor_id)
    return await stats_service.recent_checks(session, monitor_id, limit=limit, before=before)


@router.get("/{monitor_id}/response-times", response_model=ResponseTimes)
async def response_times(
    monitor_id: MonitorId,
    session: SessionDep,
    range_: Annotated[stats_service.ChartRange, Query(alias="range")] = "24h",
) -> ResponseTimes:
    await _get_monitor_or_404(session, monitor_id)
    bucket_seconds, points = await stats_service.response_time_buckets(session, monitor_id, range_)
    return ResponseTimes(
        range=range_,
        bucket_seconds=bucket_seconds,
        points=[ResponseTimePoint.model_validate(p) for p in points],
    )


@router.get("/{monitor_id}/incidents", response_model=list[IncidentOut])
async def list_incidents(
    monitor_id: MonitorId,
    session: SessionDep,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> list:
    await _get_monitor_or_404(session, monitor_id)
    return await stats_service.incident_history(session, monitor_id, limit=limit)


@router.patch("/{monitor_id}", response_model=MonitorOut)
async def update_monitor(monitor_id: MonitorId, payload: MonitorUpdate, session: SessionDep) -> Monitor:
    monitor = await _get_monitor_or_404(session, monitor_id)
    if "url" in payload.model_fields_set:
        payload.url = await _validate_url_or_422(payload.url)
    await monitor_service.apply_update(session, monitor, payload)
    await session.commit()
    await session.refresh(monitor)
    return monitor


@router.delete("/{monitor_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_monitor(monitor_id: MonitorId, session: SessionDep) -> Response:
    monitor = await _get_monitor_or_404(session, monitor_id)
    await session.delete(monitor)  # checks + incidents removed by ON DELETE CASCADE
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
