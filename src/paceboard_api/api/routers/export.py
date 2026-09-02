"""Scoped CSV/JSON exports and personal-data deletion.

Exports are intentionally scoped rather than a single "download everything"
button: each dataset is a small, named table with an explicit date window, which
keeps the file understandable and keeps an accidental full-history dump off a
single click.
"""

from __future__ import annotations

import csv
import io
import json
from datetime import datetime
from typing import Any, Iterable

from fastapi import APIRouter, Query
from fastapi.responses import Response, StreamingResponse
from sqlalchemy import select

from ...db.models import (
    Activity,
    ActivityLap,
    Base,
    DailyHealth,
    DerivedMetric,
    HrvRecord,
    PerformanceMetric,
    RawPayload,
    SleepRecord,
    StressRecord,
    TrainingLoadRecord,
)
from ...db.session import get_engine
from ..deps import DateRangeDep, SessionDep
from ..errors import bad_request

router = APIRouter(tags=["export"])

DATASETS = {
    "activities": (Activity, "start_time_utc"),
    "activity_laps": (ActivityLap, "start_time_utc"),
    "daily_health": (DailyHealth, "day"),
    "sleep": (SleepRecord, "day"),
    "hrv": (HrvRecord, "day"),
    "stress": (StressRecord, "day"),
    "training_load": (TrainingLoadRecord, "day"),
    "performance_metrics": (PerformanceMetric, "day"),
    "derived_metrics": (DerivedMetric, None),
    "raw_payloads": (RawPayload, "retrieved_at"),
}

#: Never leaves the backend, even in an export the user asked for.
EXCLUDED_COLUMNS = {"serial_number"}


@router.get("/export/datasets", response_model=list[dict], summary="Exportable datasets")
def list_datasets() -> list[dict[str, Any]]:
    return [
        {"name": name, "table": model.__tablename__, "date_column": column}
        for name, (model, column) in sorted(DATASETS.items())
    ]


@router.get("/export.csv", summary="Export one dataset as CSV")
def export_csv(
    session: SessionDep,
    window: DateRangeDep,
    dataset: str = Query(..., description="Dataset name from /export/datasets"),
) -> StreamingResponse:
    rows, columns = _query(session, dataset, window)
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=columns, extrasaction="ignore")
    writer.writeheader()
    for row in rows:
        writer.writerow({c: _cell(getattr(row, c, None)) for c in columns})
    filename = f"paceboard-{dataset}-{window.start}-{window.end}.csv"
    return StreamingResponse(
        iter([buffer.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/export.json", summary="Export one dataset as JSON")
def export_json(
    session: SessionDep,
    window: DateRangeDep,
    dataset: str = Query(...),
) -> Response:
    rows, columns = _query(session, dataset, window)
    payload = {
        "dataset": dataset,
        "exported_at": datetime.utcnow().isoformat(),
        "range": {"start": window.start.isoformat(), "end": window.end.isoformat()},
        "rows": [{c: _cell(getattr(row, c, None)) for c in columns} for row in rows],
    }
    filename = f"paceboard-{dataset}-{window.start}-{window.end}.json"
    return Response(
        content=json.dumps(payload, indent=2, default=str),
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def _query(session, dataset: str, window) -> tuple[Iterable[Any], list[str]]:
    entry = DATASETS.get(dataset)
    if entry is None:
        raise bad_request(
            f"Unknown dataset {dataset!r}", {"available": sorted(DATASETS)}
        )
    model, date_column = entry
    stmt = select(model)
    if date_column is not None:
        column = getattr(model, date_column)
        if "time" in date_column or date_column.endswith("_at"):
            stmt = stmt.where(
                column >= datetime.combine(window.start, datetime.min.time()),
                column <= datetime.combine(window.end, datetime.max.time()),
            )
        else:
            stmt = stmt.where(column >= window.start, column <= window.end)
        stmt = stmt.order_by(column)
    columns = [
        c.name for c in model.__table__.columns if c.name not in EXCLUDED_COLUMNS
    ]
    return session.execute(stmt.limit(50000)).scalars().all(), columns


def _cell(value: Any) -> Any:
    if isinstance(value, (dict, list)):
        return json.dumps(value, default=str)
    if isinstance(value, (bytes, bytearray)):
        return f"<{len(value)} bytes>"
    return value


@router.delete("/data", response_model=dict, summary="Delete stored personal data")
def clear_data(
    session: SessionDep,
    scope: str = Query(..., pattern="^(raw|derived|all)$"),
    confirm: str = Query(..., description="Must equal the scope to proceed"),
) -> dict[str, Any]:
    """Destructive, and gated on the caller repeating the scope back.

    ``raw`` drops stored provider payloads only; ``derived`` drops computed
    metrics; ``all`` empties every data table but leaves the schema and settings
    in place so the app still starts.
    """
    if confirm != scope:
        raise bad_request("confirm must equal the scope value")

    deleted: dict[str, int] = {}
    if scope in {"raw", "all"}:
        deleted["raw_payloads"] = session.query(RawPayload).delete()
    if scope in {"derived", "all"}:
        deleted["derived_metrics"] = session.query(DerivedMetric).delete()
    if scope == "all":
        engine = get_engine()
        keep = {"alembic_version", "app_settings", "raw_payloads", "derived_metrics"}
        for table in reversed(Base.metadata.sorted_tables):
            if table.name in keep:
                continue
            deleted[table.name] = session.execute(table.delete()).rowcount or 0
        engine.dispose()
    session.commit()
    return {"scope": scope, "deleted": deleted}
