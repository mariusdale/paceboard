"""Sync control: trigger, inspect progress, cancel."""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, BackgroundTasks
from sqlalchemy import select

from ...db.models import SyncError, SyncRun
from ...ingest.sync import SyncRequest, request_cancel, run_sync
from ...logging_conf import get_logger
from ..deps import PaginationDep, SessionDep
from ..errors import conflict, not_found
from ..schemas import SyncRequestBody, SyncRunResponse

router = APIRouter(prefix="/sync", tags=["sync"])
log = get_logger("paceboard.api.sync")

#: One sync at a time. Concurrent runs against the same provider would duplicate
#: work and multiply the rate-limit pressure for no gain.
_lock = asyncio.Lock()


async def _run_guarded(request: SyncRequest) -> None:
    if _lock.locked():
        log.info("Skipping sync: another run is already in progress")
        return
    async with _lock:
        try:
            await run_sync(request)
        except Exception:
            log.exception("Sync run failed")


@router.post("", response_model=dict, summary="Start a sync run")
async def start_sync(
    body: SyncRequestBody, session: SessionDep, background: BackgroundTasks
) -> dict[str, Any]:
    running = session.execute(
        select(SyncRun).where(SyncRun.status == "running").limit(1)
    ).scalar_one_or_none()
    if running is not None or _lock.locked():
        raise conflict(
            f"A sync is already running (run {running.id})" if running
            else "A sync is already running"
        )
    request = SyncRequest(
        providers=tuple(body.providers),
        mode=body.mode,
        categories=tuple(body.categories),
        start=body.start,
        end=body.end,
        trigger="manual",
        enrich=body.enrich,
    )
    background.add_task(_run_guarded, request)
    return {
        "accepted": True,
        "mode": request.mode,
        "providers": list(request.providers),
        "message": "Sync started; poll GET /api/v1/sync/latest for progress.",
    }


@router.get("", response_model=list[SyncRunResponse], summary="Recent sync runs")
def list_runs(session: SessionDep, page: PaginationDep) -> list[SyncRunResponse]:
    rows = session.execute(
        select(SyncRun).order_by(SyncRun.started_at.desc())
        .limit(page.limit).offset(page.offset)
    ).scalars().all()
    return [SyncRunResponse.model_validate(row) for row in rows]


@router.get("/latest", response_model=SyncRunResponse | None,
            summary="Most recent sync run")
def latest_run(session: SessionDep) -> SyncRunResponse | None:
    row = session.execute(
        select(SyncRun).order_by(SyncRun.started_at.desc()).limit(1)
    ).scalar_one_or_none()
    return _with_errors(session, row) if row else None


@router.get("/{run_id}", response_model=SyncRunResponse, summary="One sync run")
def get_run(run_id: int, session: SessionDep) -> SyncRunResponse:
    row = session.get(SyncRun, run_id)
    if row is None:
        raise not_found("Sync run", run_id)
    return _with_errors(session, row)


@router.post("/{run_id}/cancel", response_model=dict, summary="Cancel a running sync")
def cancel_run(run_id: int, session: SessionDep) -> dict[str, Any]:
    row = session.get(SyncRun, run_id)
    if row is None:
        raise not_found("Sync run", run_id)
    if row.status != "running":
        raise conflict(f"Sync run {run_id} is {row.status}, not running")
    accepted = request_cancel(run_id)
    return {"accepted": accepted, "run_id": run_id}


def _with_errors(session, row: SyncRun) -> SyncRunResponse:
    errors = session.execute(
        select(SyncError).where(SyncError.sync_run_id == row.id)
        .order_by(SyncError.occurred_at.desc()).limit(50)
    ).scalars().all()
    response = SyncRunResponse.model_validate(row)
    response.errors = [
        {
            "provider": e.provider, "capability": e.capability, "kind": e.kind,
            "message": e.message, "occurred_at": e.occurred_at.isoformat(),
        }
        for e in errors
    ]
    return response
