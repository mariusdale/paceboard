"""Training load, performance metrics, volume and consistency."""

from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Query
from sqlalchemy import select

from ...analytics import service as analytics
from ...db.models import PerformanceMetric, TrainingStatusRecord
from ..deps import DateRangeDep, SessionDep

router = APIRouter(prefix="/training", tags=["training"])


@router.get("/load", response_model=dict, summary="CTL/ATL/TSB and provider load")
def load(session: SessionDep, window: DateRangeDep) -> dict[str, Any]:
    series = analytics.load_series(session, window.start, window.end)
    series["formula"] = {
        "ctl": "Exponentially weighted 42-day average of daily TRIMP",
        "atl": "Exponentially weighted 7-day average of daily TRIMP",
        "tsb": "CTL - ATL (form)",
        "daily_load": "Sum of Banister TRIMP per activity; falls back to Garmin "
                      "training load when heart rate is missing",
        "formula_version": analytics.F.FORMULA_VERSION,
    }
    series["provider_note"] = (
        "Garmin's acute/chronic load uses Garmin's own units and is shown "
        "alongside, not blended into, Paceboard's TRIMP-based series."
    )
    return series


@router.get("/status", response_model=list[dict], summary="Garmin training status")
def status(session: SessionDep, window: DateRangeDep) -> list[dict[str, Any]]:
    rows = session.execute(
        select(TrainingStatusRecord).where(
            TrainingStatusRecord.day >= window.start,
            TrainingStatusRecord.day <= window.end,
        ).order_by(TrainingStatusRecord.day)
    ).scalars().all()
    return [
        {
            "day": row.day.isoformat(), "source": row.source,
            "status_code": row.status_code, "status_label": row.status_label,
            "feedback": row.feedback, "fitness_trend": row.fitness_trend,
            "acwr": row.acwr, "acwr_status": row.acwr_status,
            "load_aerobic_low": row.load_aerobic_low,
            "load_aerobic_high": row.load_aerobic_high,
            "load_anaerobic": row.load_anaerobic,
            "balance_feedback": row.balance_feedback,
        }
        for row in rows
    ]


@router.get("/performance", response_model=dict, summary="Performance metric series")
def performance(
    session: SessionDep,
    window: DateRangeDep,
    metric: Optional[str] = Query(None, description="Filter to a single metric name"),
) -> dict[str, Any]:
    stmt = select(PerformanceMetric).where(
        PerformanceMetric.day >= window.start, PerformanceMetric.day <= window.end
    )
    if metric:
        stmt = stmt.where(PerformanceMetric.metric == metric)
    rows = session.execute(
        stmt.order_by(PerformanceMetric.metric, PerformanceMetric.day)
    ).scalars().all()
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        key = row.metric if row.sport == "generic" else f"{row.metric}:{row.sport}"
        grouped.setdefault(key, []).append({
            "day": row.day.isoformat(), "value": row.value,
            "display": row.text_value, "units": row.units,
            "source": row.source, "context": row.context,
        })
    return {
        "metrics": grouped,
        "available": bool(grouped),
        "unavailable_reason": None if grouped
        else "No performance metrics recorded for this window",
    }


@router.get("/volume", response_model=list[dict], summary="Weekly volume by sport")
def volume(session: SessionDep, window: DateRangeDep) -> list[dict[str, Any]]:
    return analytics.weekly_volume(session, window.start, window.end)


@router.get("/zones", response_model=dict, summary="Time in heart-rate or power zones")
def zones(
    session: SessionDep,
    window: DateRangeDep,
    kind: str = Query("hr", pattern="^(hr|power)$"),
) -> dict[str, Any]:
    return analytics.zone_totals(session, window.start, window.end, kind)


@router.get("/rolling", response_model=list[dict], summary="Rolling totals")
def rolling(session: SessionDep) -> list[dict[str, Any]]:
    return [analytics.rolling_totals(session, days) for days in (7, 28, 90, 365)]


@router.get("/consistency", response_model=dict, summary="Activity consistency and streaks")
def consistency(session: SessionDep,
                days: int = Query(90, ge=7, le=730)) -> dict[str, Any]:
    return analytics.consistency(session, window_days=days)


@router.get("/monotony", response_model=dict, summary="Monotony and strain")
def monotony(session: SessionDep) -> dict[str, Any]:
    return {
        name: value.as_dict()
        for name, value in analytics.monotony_and_strain(session).items()
    }


@router.get("/records", response_model=list[dict], summary="Personal records")
def records(session: SessionDep) -> list[dict[str, Any]]:
    return analytics.personal_records(session)
