"""Daily health, sleep, HRV, stress and body-battery series."""

from __future__ import annotations

from typing import Any, Optional
from datetime import date

from fastapi import APIRouter, Query
from sqlalchemy import select

from ...analytics import service as analytics
from ...db.models import (
    BodyBatteryRecord,
    BodyComposition,
    DailyHealth,
    HrvRecord,
    SleepRecord,
    StressRecord,
)
from ..deps import DateRangeDep, SessionDep

router = APIRouter(prefix="/health", tags=["health"])


def _rows(session, model, window, source: Optional[str]):
    stmt = select(model).where(model.day >= window.start, model.day <= window.end)
    if source:
        stmt = stmt.where(model.source == source)
    return session.execute(stmt.order_by(model.day)).scalars().all()


def _serialize(rows, fields: tuple[str, ...]) -> list[dict[str, Any]]:
    return [
        {"day": row.day.isoformat(), "source": row.source,
         **{f: getattr(row, f) for f in fields}}
        for row in rows
    ]


DAILY_FIELDS = (
    "steps", "step_goal", "distance_m", "floors_ascended", "total_calories",
    "active_calories", "moderate_intensity_minutes", "vigorous_intensity_minutes",
    "intensity_minutes_goal", "resting_hr", "min_hr", "max_hr", "avg_hr",
    "rhr_7day_avg", "avg_stress", "max_stress", "body_battery_high",
    "body_battery_low", "body_battery_charged", "body_battery_drained",
    "avg_waking_respiration", "avg_sleep_respiration", "spo2_avg", "spo2_lowest",
    "training_readiness", "readiness_level", "readiness_factors",
)

SLEEP_FIELDS = (
    "sleep_start_utc", "sleep_end_utc", "total_sleep_s", "nap_s", "deep_s",
    "light_s", "rem_s", "awake_s", "awake_count", "sleep_score",
    "score_qualifier", "avg_sleep_stress", "avg_overnight_hrv",
)

HRV_FIELDS = (
    "last_night_avg_ms", "last_night_5min_high_ms", "weekly_avg_ms",
    "baseline_balanced_low_ms", "baseline_balanced_upper_ms", "status", "feedback",
)

STRESS_FIELDS = (
    "avg_stress", "max_stress", "rest_pct", "low_pct", "medium_pct", "high_pct",
    "data_points",
)


@router.get("/daily", response_model=list[dict], summary="Daily health records")
def daily(session: SessionDep, window: DateRangeDep,
          source: Optional[str] = Query(None)) -> list[dict[str, Any]]:
    return _serialize(_rows(session, DailyHealth, window, source), DAILY_FIELDS)


@router.get("/sleep", response_model=list[dict], summary="Sleep records")
def sleep(session: SessionDep, window: DateRangeDep,
          source: Optional[str] = Query(None)) -> list[dict[str, Any]]:
    return _serialize(_rows(session, SleepRecord, window, source), SLEEP_FIELDS)


@router.get("/hrv", response_model=list[dict], summary="HRV records")
def hrv(session: SessionDep, window: DateRangeDep,
        source: Optional[str] = Query(None)) -> list[dict[str, Any]]:
    return _serialize(_rows(session, HrvRecord, window, source), HRV_FIELDS)


@router.get("/stress", response_model=list[dict], summary="Stress records")
def stress(session: SessionDep, window: DateRangeDep,
           source: Optional[str] = Query(None)) -> list[dict[str, Any]]:
    return _serialize(_rows(session, StressRecord, window, source), STRESS_FIELDS)


@router.get("/body-battery", response_model=list[dict], summary="Body Battery records")
def body_battery(session: SessionDep, window: DateRangeDep,
                 source: Optional[str] = Query(None)) -> list[dict[str, Any]]:
    return _serialize(
        _rows(session, BodyBatteryRecord, window, source),
        ("charged", "drained", "highest", "lowest", "level_label", "feedback"),
    )


@router.get("/body-composition", response_model=list[dict], summary="Body composition")
def body_composition(session: SessionDep, window: DateRangeDep,
                     source: Optional[str] = Query(None)) -> list[dict[str, Any]]:
    return _serialize(
        _rows(session, BodyComposition, window, source),
        ("weight_kg", "bmi", "body_fat_pct", "body_water_pct", "muscle_mass_kg"),
    )


@router.get("/recovery", response_model=dict, summary="Recovery series with baselines")
def recovery(session: SessionDep, window: DateRangeDep) -> dict[str, Any]:
    return analytics.recovery_series(session, window.start, window.end)


@router.get("/recovery/summary", response_model=dict, summary="Recovery headline metrics")
def recovery_summary(session: SessionDep, end: Optional[date] = Query(None)) -> dict[str, Any]:
    return analytics.recovery_summary(session, end=end)


@router.get("/correlations", response_model=list[dict],
            summary="Recovery vs load correlations")
def correlations(session: SessionDep,
                 days: int = Query(90, ge=14, le=1100),
                 end: Optional[date] = Query(None)) -> list[dict[str, Any]]:
    return analytics.correlations(session, end=end, window_days=days)
