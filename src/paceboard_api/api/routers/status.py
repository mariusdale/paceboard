"""Status, connections and capability catalog routes."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Query
from sqlalchemy import func, select

from ... import __version__
from ...db.models import (
    Activity,
    ActivitySourceRecord,
    DailyHealth,
    ProviderCapability,
    ProviderConnection,
    RawPayload,
    SleepRecord,
    SyncRun,
    SyncWatermark,
)
from ...providers.garmin import catalog
from ...providers.registry import get_registry
from ...providers.strava.mcp_provider import StravaMcpProvider
from ..deps import SessionDep, SettingsDep
from ..schemas import CapabilityResponse, ConnectionResponse, StatusResponse

router = APIRouter(tags=["status"])

_COUNTED = {
    "activities": Activity,
    "activity_source_records": ActivitySourceRecord,
    "daily_health": DailyHealth,
    "sleep_records": SleepRecord,
    "raw_payloads": RawPayload,
}


@router.get("/status", response_model=StatusResponse, summary="Application status")
def get_status(session: SessionDep, settings: SettingsDep) -> StatusResponse:
    counts = {
        name: session.execute(select(func.count()).select_from(model)).scalar_one()
        for name, model in _COUNTED.items()
    }
    last_run = session.execute(
        select(SyncRun).order_by(SyncRun.started_at.desc()).limit(1)
    ).scalar_one_or_none()
    database_bytes = (
        settings.database_path.stat().st_size if settings.database_path.exists() else 0
    )
    return StatusResponse(
        version=__version__,
        timezone=settings.timezone,
        unit_system=settings.unit_system,
        fixture_mode=settings.fixture_mode,
        database_path=str(settings.database_path),
        database_bytes=database_bytes,
        bound_host=settings.host,
        api_port=settings.api_port,
        counts=counts,
        last_sync=_run_brief(last_run),
        freshness=_freshness(session),
    )


def _run_brief(run: SyncRun | None) -> dict[str, Any] | None:
    if run is None:
        return None
    return {
        "id": run.id,
        "status": run.status,
        "mode": run.mode,
        "started_at": run.started_at.isoformat(),
        "finished_at": run.finished_at.isoformat() if run.finished_at else None,
        "records_written": run.records_written,
        "errors_count": run.errors_count,
        "current_step": run.current_step,
    }


def _freshness(session) -> list[dict[str, Any]]:
    """Per-provider/category recency, used for the "stale data" UI states."""
    rows = session.execute(select(SyncWatermark)).scalars().all()
    now = datetime.utcnow()
    out = []
    for row in rows:
        age = (now - row.last_success_at).total_seconds() if row.last_success_at else None
        out.append({
            "provider": row.provider,
            "category": row.category,
            "cursor_date": row.cursor_date.isoformat() if row.cursor_date else None,
            "last_success_at": row.last_success_at.isoformat()
            if row.last_success_at else None,
            "age_seconds": int(age) if age is not None else None,
            "status": row.last_status,
        })
    return out


@router.get("/connections", response_model=list[ConnectionResponse],
            summary="Provider connection state")
def get_connections(session: SessionDep, settings: SettingsDep) -> list[ConnectionResponse]:
    stored = {
        row.provider: row
        for row in session.execute(select(ProviderConnection)).scalars()
    }
    registry = get_registry()
    out: list[ConnectionResponse] = []

    garmin = stored.get("garmin")
    out.append(
        ConnectionResponse(
            provider="garmin",
            status=garmin.status if garmin else "unknown",
            display_name=garmin.display_name if garmin else None,
            endpoint=settings.garmin_mcp_url,
            configured=True,
            last_checked_at=garmin.last_checked_at if garmin else None,
            last_success_at=garmin.last_success_at if garmin else None,
            last_error=garmin.last_error if garmin else None,
            details={"transport": "streamable-http", "read_only": True,
                     "allowlisted_tools": len(catalog.READ_ONLY_ALLOWLIST)},
        )
    )

    strava = stored.get("strava")
    tokens = registry.strava.client.store.load() if registry.strava.configured else None
    out.append(
        ConnectionResponse(
            provider="strava",
            status=(
                "connected" if tokens is not None
                else "not_configured" if not registry.strava.configured
                else "not_connected"
            ),
            display_name=tokens.athlete_name if tokens else None,
            endpoint="https://www.strava.com/api/v3",
            configured=registry.strava.configured,
            last_checked_at=strava.last_checked_at if strava else None,
            last_success_at=strava.last_success_at if strava else None,
            last_error=strava.last_error if strava else None,
            details={
                "token": tokens.public_view() if tokens else None,
                "tokens_encrypted": registry.strava.client.store.encrypted,
                "rate_limit": registry.strava.client.rate_limit.as_dict(),
                "mcp_alternative": StravaMcpProvider.availability(),
            },
        )
    )
    return out


@router.get("/capabilities", response_model=list[CapabilityResponse],
            summary="Provider capability catalog")
def get_capabilities(
    session: SessionDep,
    provider: str | None = Query(None),
    status: str | None = Query(None),
    category: str | None = Query(None),
) -> list[CapabilityResponse]:
    stmt = select(ProviderCapability)
    if provider:
        stmt = stmt.where(ProviderCapability.provider == provider)
    if status:
        stmt = stmt.where(ProviderCapability.status == status)
    if category:
        stmt = stmt.where(ProviderCapability.category == category)
    rows = session.execute(
        stmt.order_by(ProviderCapability.provider, ProviderCapability.category,
                      ProviderCapability.name)
    ).scalars().all()
    return [CapabilityResponse.model_validate(row) for row in rows]
