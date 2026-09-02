"""Activity list, detail, streams, laps, zones and duplicate review."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from fastapi import APIRouter, Query
from sqlalchemy import func, select

from ...analytics import service as analytics
from ...db.models import (
    Activity,
    ActivityLap,
    ActivitySourceRecord,
    ActivitySplit,
    ActivityZone,
    DuplicateCandidate,
)
from ...ingest.activities import load_streams
from ...ingest.dedupe import resolve_candidate
from ..deps import PaginationDep, SessionDep
from ..errors import bad_request, not_found
from ..schemas import (
    ActivityListResponse,
    ActivityResponse,
    LapResponse,
    Page,
)

router = APIRouter(prefix="/activities", tags=["activities"])

#: Charts do not benefit from more than a few thousand points, and shipping a
#: 20k-sample series to the browser makes the detail page sluggish.
MAX_STREAM_POINTS = 3000


@router.get("", response_model=ActivityListResponse, summary="List activities")
def list_activities(
    session: SessionDep,
    page: PaginationDep,
    sport: Optional[str] = Query(None, description="Canonical sport, e.g. run/ride"),
    source: Optional[str] = Query(None, description="garmin | strava"),
    search: Optional[str] = Query(None, max_length=200),
    start: Optional[str] = Query(None, description="Inclusive start date"),
    end: Optional[str] = Query(None, description="Inclusive end date"),
    has_gps: Optional[bool] = Query(None),
    duplicates_only: bool = Query(False),
) -> ActivityListResponse:
    stmt = select(Activity)
    count_stmt = select(func.count()).select_from(Activity)

    filters = []
    if sport:
        filters.append(Activity.sport == sport)
    if has_gps is not None:
        filters.append(Activity.has_gps.is_(has_gps))
    if duplicates_only:
        filters.append(Activity.duplicate_state == "merged")
    if search:
        filters.append(Activity.name.ilike(f"%{search}%"))
    if start:
        filters.append(Activity.start_time_utc >= _parse_day(start, "start"))
    if end:
        filters.append(
            Activity.start_time_utc
            <= datetime.combine(_parse_day(end, "end").date(), datetime.max.time())
        )
    if source:
        if source not in {"garmin", "strava"}:
            raise bad_request("source must be 'garmin' or 'strava'")
        subquery = select(ActivitySourceRecord.activity_id).where(
            ActivitySourceRecord.source == source
        )
        filters.append(Activity.id.in_(subquery))

    for condition in filters:
        stmt = stmt.where(condition)
        count_stmt = count_stmt.where(condition)

    total = session.execute(count_stmt).scalar_one()
    rows = session.execute(
        stmt.order_by(Activity.start_time_utc.desc())
        .limit(page.limit).offset(page.offset)
    ).scalars().all()
    return ActivityListResponse(
        items=[ActivityResponse.model_validate(row) for row in rows],
        page=Page(
            total=total, limit=page.limit, offset=page.offset,
            has_more=page.offset + len(rows) < total,
        ),
    )


def _parse_day(value: str, label: str) -> datetime:
    try:
        return datetime.fromisoformat(value[:10])
    except ValueError as exc:
        raise bad_request(f"{label} must be an ISO date (YYYY-MM-DD)") from exc


@router.get("/duplicates", response_model=list[dict], summary="Uncertain duplicate matches")
def list_duplicates(session: SessionDep, state: str = Query("pending")) -> list[dict[str, Any]]:
    rows = session.execute(
        select(DuplicateCandidate).where(DuplicateCandidate.state == state)
        .order_by(DuplicateCandidate.score.desc())
    ).scalars().all()
    out: list[dict[str, Any]] = []
    for row in rows:
        left = session.get(ActivitySourceRecord, row.left_source_record_id)
        right = session.get(ActivitySourceRecord, row.right_source_record_id)
        if left is None or right is None:
            continue
        out.append({
            "id": row.id,
            "score": round(row.score, 3),
            "state": row.state,
            "reasons": row.reasons,
            "left": _source_brief(left),
            "right": _source_brief(right),
        })
    return out


def _source_brief(row: ActivitySourceRecord) -> dict[str, Any]:
    return {
        "source": row.source,
        "provider_id": row.provider_id,
        "activity_id": row.activity_id,
        "name": row.name,
        "sport": row.sport,
        "start_time_utc": row.start_time_utc.isoformat(),
        "duration_s": row.duration_s,
        "distance_m": row.distance_m,
    }


@router.post("/duplicates/{candidate_id}", response_model=dict,
             summary="Confirm or reject a duplicate match")
def decide_duplicate(candidate_id: int, session: SessionDep,
                     accept: bool = Query(...)) -> dict[str, Any]:
    if session.get(DuplicateCandidate, candidate_id) is None:
        raise not_found("Duplicate candidate", candidate_id)
    activity = resolve_candidate(session, candidate_id, accept)
    session.commit()
    return {"resolved": True, "accepted": accept,
            "activity_id": activity.id if activity else None}


@router.get("/{activity_id}", response_model=ActivityResponse, summary="Activity detail")
def get_activity(activity_id: int, session: SessionDep) -> ActivityResponse:
    row = session.get(Activity, activity_id)
    if row is None:
        raise not_found("Activity", activity_id)
    return ActivityResponse.model_validate(row)


@router.get("/{activity_id}/laps", response_model=list[LapResponse], summary="Laps")
def get_laps(activity_id: int, session: SessionDep) -> list[LapResponse]:
    if session.get(Activity, activity_id) is None:
        raise not_found("Activity", activity_id)
    rows = session.execute(
        select(ActivityLap).where(ActivityLap.activity_id == activity_id)
        .order_by(ActivityLap.source, ActivityLap.lap_index)
    ).scalars().all()
    return [LapResponse.model_validate(row) for row in rows]


@router.get("/{activity_id}/splits", response_model=list[dict], summary="Typed splits")
def get_splits(activity_id: int, session: SessionDep) -> list[dict[str, Any]]:
    rows = session.execute(
        select(ActivitySplit).where(ActivitySplit.activity_id == activity_id)
        .order_by(ActivitySplit.split_type, ActivitySplit.split_index)
    ).scalars().all()
    return [
        {
            "source": row.source, "split_type": row.split_type,
            "split_index": row.split_index, "distance_m": row.distance_m,
            "duration_s": row.duration_s, "elevation_gain_m": row.elevation_gain_m,
            "avg_speed_mps": row.avg_speed_mps, "avg_hr": row.avg_hr,
            "details": row.details,
        }
        for row in rows
    ]


@router.get("/{activity_id}/zones", response_model=dict, summary="Time in zones")
def get_zones(activity_id: int, session: SessionDep) -> dict[str, Any]:
    rows = session.execute(
        select(ActivityZone).where(ActivityZone.activity_id == activity_id)
        .order_by(ActivityZone.zone_kind, ActivityZone.zone_number)
    ).scalars().all()
    if not rows:
        return {"available": False,
                "unavailable_reason": "No zone data recorded for this activity",
                "zones": []}
    return {
        "available": True,
        "unavailable_reason": None,
        "zones": [
            {
                "source": row.source, "kind": row.zone_kind, "zone": row.zone_number,
                "seconds": row.seconds_in_zone, "low": row.low_boundary,
                "high": row.high_boundary,
            }
            for row in rows
        ],
    }


@router.get("/{activity_id}/streams", response_model=dict, summary="Per-sample streams")
def get_streams(
    activity_id: int,
    session: SessionDep,
    channels: Optional[str] = Query(None, description="Comma-separated channel names"),
    max_points: int = Query(MAX_STREAM_POINTS, ge=50, le=20000),
) -> dict[str, Any]:
    activity = session.get(Activity, activity_id)
    if activity is None:
        raise not_found("Activity", activity_id)
    wanted = [c.strip() for c in channels.split(",")] if channels else None
    streams = load_streams(session, activity_id, wanted)
    if not streams:
        return {
            "activity_id": activity_id, "available": False,
            "unavailable_reason": (
                "No per-sample streams stored for this activity yet"
                if activity.stream_status == "pending"
                else "The provider returned no per-sample data for this activity"
            ),
            "point_count": 0, "channels": {},
        }
    point_count = max(len(s["data"]) for s in streams.values())
    step = max(1, point_count // max_points)
    return {
        "activity_id": activity_id,
        "available": True,
        "unavailable_reason": None,
        "point_count": (point_count + step - 1) // step,
        "original_point_count": point_count,
        "downsample_step": step,
        "channels": {
            name: {
                "source": payload["source"],
                "units": payload["units"],
                "data": payload["data"][::step],
            }
            for name, payload in streams.items()
        },
    }


@router.get("/{activity_id}/analysis", response_model=dict,
            summary="Derived analysis for one activity")
def get_analysis(activity_id: int, session: SessionDep) -> dict[str, Any]:
    activity = session.get(Activity, activity_id)
    if activity is None:
        raise not_found("Activity", activity_id)
    metrics = analytics.activity_stream_metrics(session, activity)
    metrics["trimp"] = analytics.activity_trimp(session, activity)
    return {
        "activity_id": activity_id,
        "metrics": {name: value.as_dict() for name, value in metrics.items()},
        "source_comparison": _source_comparison(session, activity),
    }


COMPARED_FIELDS = (
    "distance_m", "duration_s", "moving_duration_s", "elevation_gain_m",
    "avg_hr", "max_hr", "avg_speed_mps", "calories", "avg_power_w",
)


def _source_comparison(session, activity: Activity) -> dict[str, Any]:
    """Side-by-side provider values, so disagreements are visible, not hidden."""
    sources = list(activity.sources)
    if len(sources) < 2:
        return {"available": False,
                "unavailable_reason": "Only one provider recorded this activity",
                "fields": []}
    fields = []
    for field in COMPARED_FIELDS:
        values = {row.source: (row.summary or {}).get(field) for row in sources}
        present = [v for v in values.values() if isinstance(v, (int, float))]
        if len(present) < 2:
            continue
        spread = max(present) - min(present)
        fields.append({
            "field": field,
            "values": values,
            "difference": spread,
            "difference_pct": round(spread / max(present) * 100, 2) if max(present) else None,
            "chosen_source": (activity.field_provenance or {}).get(field),
        })
    return {"available": True, "unavailable_reason": None, "fields": fields}
