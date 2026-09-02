"""Data Explorer: raw payload browsing and guarded manual tool invocation."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from fastapi import APIRouter, Query
from sqlalchemy import func, select

from ...db.models import RawPayload
from ...ingest.raw_store import store_result
from ...logging_conf import get_logger
from ...providers.base import ProviderUnavailable
from ...providers.garmin import catalog
from ...providers.registry import get_registry
from ..deps import PaginationDep, SessionDep
from ..errors import bad_request, not_found, unavailable
from ..schemas import RawPayloadDetail, RawPayloadResponse, ToolCallRequest

router = APIRouter(tags=["raw-data"])
log = get_logger("paceboard.api.raw")

#: A single manual call must not be able to pull an unbounded window.
MAX_ARGUMENT_CHARS = 512


@router.get("/raw-data", response_model=dict, summary="Browse stored raw payloads")
def list_raw(
    session: SessionDep,
    page: PaginationDep,
    provider: Optional[str] = Query(None),
    endpoint: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    reference_id: Optional[str] = Query(None),
) -> dict[str, Any]:
    stmt = select(RawPayload)
    count_stmt = select(func.count()).select_from(RawPayload)
    for condition in [
        RawPayload.provider == provider if provider else None,
        RawPayload.endpoint == endpoint if endpoint else None,
        RawPayload.status == status if status else None,
        RawPayload.reference_id == reference_id if reference_id else None,
    ]:
        if condition is not None:
            stmt = stmt.where(condition)
            count_stmt = count_stmt.where(condition)
    total = session.execute(count_stmt).scalar_one()
    rows = session.execute(
        stmt.order_by(RawPayload.retrieved_at.desc())
        .limit(page.limit).offset(page.offset)
    ).scalars().all()
    return {
        "items": [RawPayloadResponse.model_validate(r).model_dump() for r in rows],
        "page": {"total": total, "limit": page.limit, "offset": page.offset,
                 "has_more": page.offset + len(rows) < total},
        "endpoints": _endpoint_coverage(session, provider),
    }


def _endpoint_coverage(session, provider: Optional[str]) -> list[dict[str, Any]]:
    stmt = select(
        RawPayload.provider, RawPayload.endpoint, RawPayload.status,
        func.count(RawPayload.id), func.max(RawPayload.retrieved_at),
    ).group_by(RawPayload.provider, RawPayload.endpoint, RawPayload.status)
    if provider:
        stmt = stmt.where(RawPayload.provider == provider)
    return [
        {"provider": p, "endpoint": e, "status": s, "count": c,
         "last_retrieved_at": t.isoformat() if isinstance(t, datetime) else t}
        for p, e, s, c, t in session.execute(stmt).all()
    ]


@router.get("/raw-data/{payload_id}", response_model=RawPayloadDetail,
            summary="One raw payload with its content")
def get_raw(payload_id: int, session: SessionDep) -> RawPayloadDetail:
    row = session.get(RawPayload, payload_id)
    if row is None:
        raise not_found("Raw payload", payload_id)
    detail = RawPayloadDetail.model_validate(row)
    detail.content = row.content_json if row.content_json is not None else row.content_text
    return detail


@router.get("/tools", response_model=list[dict], summary="Invokable read-only tools")
def list_tools() -> list[dict[str, Any]]:
    """The exact set the manual invocation form will accept — nothing else."""
    return [
        {
            "name": spec.name,
            "category": spec.category,
            "scope": spec.scope,
            "cadence": spec.cadence,
            "arguments": list(spec.args),
            "defaults": spec.extra_args,
            "max_range_days": spec.max_range_days,
            "scheduled": spec.enabled,
            "notes": spec.notes,
        }
        for spec in sorted(catalog.TOOL_SPECS, key=lambda s: (s.category, s.name))
    ]


@router.post("/tools/call", response_model=dict, summary="Invoke one read-only tool")
async def call_tool(body: ToolCallRequest, session: SessionDep) -> dict[str, Any]:
    """Run a Garmin read tool on demand.

    Three guards, in order: the tool must be on the catalog allowlist, it must
    not match a mutating name pattern, and every argument must be one the
    catalog declares for that tool. Anything else is rejected before a request
    reaches the MCP server.
    """
    spec = catalog.TOOLS_BY_NAME.get(body.tool)
    if spec is None:
        raise bad_request(
            f"Tool {body.tool!r} is not on the Paceboard read-only allowlist",
            {"allowed": list(catalog.READ_ONLY_ALLOWLIST)[:40]},
        )
    if catalog.is_mutating(body.tool):
        raise bad_request(f"Tool {body.tool!r} is a mutating tool and cannot be invoked")

    allowed_args = set(spec.args) | set(spec.extra_args)
    unknown = sorted(set(body.arguments) - allowed_args)
    if unknown:
        raise bad_request(
            f"Unexpected argument(s) for {body.tool}: {', '.join(unknown)}",
            {"allowed": sorted(allowed_args)},
        )
    for key, value in body.arguments.items():
        if isinstance(value, str) and len(value) > MAX_ARGUMENT_CHARS:
            raise bad_request(f"Argument {key!r} is too long")

    provider = get_registry().garmin
    try:
        await provider.connect()
    except ProviderUnavailable as exc:
        raise unavailable(str(exc), {"provider": "garmin"}) from exc

    result = await provider.call_tool(body.tool, dict(spec.extra_args, **body.arguments))
    raw = store_result(session, result, reference_kind="manual")
    session.commit()
    return {
        "tool": body.tool,
        "arguments": result.params,
        "status": result.status.value,
        "message": result.message,
        "duration_ms": result.duration_ms,
        "raw_payload_id": raw.id,
        "content": result.data if result.data is not None else result.text,
    }
