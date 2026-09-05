"""Garmin response handlers: curated MCP JSON -> normalized rows.

One function per ``handler`` name declared in the tool catalog. Each returns the
number of rows it wrote, so the sync run can report real progress. Handlers are
deliberately defensive — a Garmin field that is absent stays ``None`` and is
rendered as "Unavailable" in the UI rather than silently becoming zero.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Callable, Optional

from sqlalchemy.orm import Session

from ..db.models import (
    Athlete,
    BodyBatteryRecord,
    BodyComposition,
    DailyHealth,
    Device,
    Gear,
    HeartRateZoneSet,
    HrvRecord,
    PerformanceMetric,
    SleepRecord,
    StressRecord,
    TrainingLoadRecord,
    TrainingStatusRecord,
)
from ..logging_conf import get_logger
from ..providers.dto import ProviderResult
from .upsert import upsert

log = get_logger("paceboard.normalize.garmin")

SOURCE = "garmin"

Handler = Callable[[Session, ProviderResult, Optional[int]], int]
_HANDLERS: dict[str, Handler] = {}


def handler(name: str) -> Callable[[Handler], Handler]:
    def register(fn: Handler) -> Handler:
        _HANDLERS[name] = fn
        return fn

    return register


def get_handler(name: Optional[str]) -> Optional[Handler]:
    return _HANDLERS.get(name) if name else None


def handler_names() -> list[str]:
    return sorted(_HANDLERS)


# -- helpers ---------------------------------------------------------------


def _as_date(value: Any) -> Optional[date]:
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    if not value:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _requested_date(result: ProviderResult) -> Optional[date]:
    for key in ("date", "end_date", "start_date"):
        parsed = _as_date(result.params.get(key))
        if parsed:
            return parsed
    return None


def _day_of(result: ProviderResult, payload: Any = None) -> Optional[date]:
    """Prefer the date Garmin reported; fall back to the date we asked for."""
    if isinstance(payload, dict):
        for key in ("date", "calendar_date", "calendarDate", "day"):
            parsed = _as_date(payload.get(key))
            if parsed:
                return parsed
    return _requested_date(result)


def _dt(value: Any) -> Optional[datetime]:
    from ..providers.garmin.provider import _parse_dt

    return _parse_dt(value)


def _num(value: Any) -> Optional[float]:
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _int(value: Any) -> Optional[int]:
    number = _num(value)
    return int(number) if number is not None else None


def _score(value: Any) -> Optional[int]:
    number = _int(value)
    return number if number is not None and 0 <= number <= 100 else None


def _perf(
    session: Session,
    metric: str,
    day: Optional[date],
    value: Optional[float],
    *,
    sport: str = "generic",
    units: Optional[str] = None,
    text_value: Optional[str] = None,
    context: Optional[dict[str, Any]] = None,
    raw_id: Optional[int] = None,
) -> int:
    if day is None or (value is None and text_value is None):
        return 0
    upsert(
        session, PerformanceMetric,
        {"source": SOURCE, "metric": metric, "sport": sport, "day": day},
        {"value": value, "units": units, "text_value": text_value, "context": context},
        raw_payload_id=raw_id,
    )
    return 1


# -- daily health ----------------------------------------------------------


@handler("daily_stats")
def daily_stats(session: Session, result: ProviderResult, raw_id: Optional[int]) -> int:
    payload = result.data
    day = _day_of(result, payload)
    if not isinstance(payload, dict) or day is None:
        return 0
    upsert(
        session, DailyHealth, {"source": SOURCE, "day": day},
        {
            "steps": _int(payload.get("total_steps")),
            "step_goal": _int(payload.get("daily_step_goal")),
            "distance_m": _num(payload.get("distance_meters")),
            "floors_ascended": _num(payload.get("floors_ascended")),
            "total_calories": _num(payload.get("total_calories")),
            "active_calories": _num(payload.get("active_calories")),
            "bmr_calories": _num(payload.get("bmr_calories")),
            "moderate_intensity_minutes": _int(payload.get("moderate_intensity_minutes")),
            "vigorous_intensity_minutes": _int(payload.get("vigorous_intensity_minutes")),
            "intensity_minutes_goal": _int(payload.get("intensity_minutes_goal")),
            "resting_hr": _int(payload.get("resting_heart_rate_bpm")),
            "min_hr": _int(payload.get("min_heart_rate_bpm")),
            "max_hr": _int(payload.get("max_heart_rate_bpm")),
            "rhr_7day_avg": _int(payload.get("last_7_days_avg_resting_hr")),
            "avg_stress": _score(payload.get("avg_stress_level")),
            "max_stress": _score(payload.get("max_stress_level")),
            "body_battery_high": _int(payload.get("body_battery_highest")),
            "body_battery_low": _int(payload.get("body_battery_lowest")),
            "body_battery_charged": _int(payload.get("body_battery_charged")),
            "body_battery_drained": _int(payload.get("body_battery_drained")),
            "avg_waking_respiration": _num(payload.get("avg_waking_respiration")),
            "lowest_respiration": _num(payload.get("lowest_respiration")),
            "highest_respiration": _num(payload.get("highest_respiration")),
            "sleeping_seconds": _int(payload.get("sleeping_seconds")),
        },
        raw_payload_id=raw_id,
    )
    return 1


@handler("heart_rate_summary")
def heart_rate_summary(session: Session, result: ProviderResult, raw_id: Optional[int]) -> int:
    payload = result.data
    day = _day_of(result, payload)
    if not isinstance(payload, dict) or day is None:
        return 0
    upsert(
        session, DailyHealth, {"source": SOURCE, "day": day},
        {
            "resting_hr": _int(payload.get("resting_heart_rate_bpm")),
            "min_hr": _int(payload.get("min_heart_rate_bpm")),
            "max_hr": _int(payload.get("max_heart_rate_bpm")),
            "avg_hr": _num(payload.get("avg_heart_rate_bpm")),
            "rhr_7day_avg": _int(payload.get("last_7_days_avg_resting_hr")),
        },
        raw_payload_id=raw_id,
    )
    return 1


def _write_sleep(session: Session, day: date, night: dict[str, Any], raw_id: Optional[int]) -> int:
    upsert(
        session, SleepRecord, {"source": SOURCE, "day": day},
        {
            "sleep_start_utc": _dt(night.get("sleep_start")),
            "sleep_end_utc": _dt(night.get("sleep_end")),
            "total_sleep_s": _int(night.get("sleep_seconds")),
            "nap_s": _int(night.get("nap_seconds")),
            "deep_s": _int(night.get("deep_sleep_seconds")),
            "light_s": _int(night.get("light_sleep_seconds")),
            "rem_s": _int(night.get("rem_sleep_seconds")),
            "awake_s": _int(night.get("awake_seconds")),
            "awake_count": _int(night.get("awake_count")),
            "sleep_score": _int(night.get("sleep_score")),
            "score_qualifier": night.get("sleep_score_qualifier"),
            "avg_sleep_stress": _num(night.get("avg_sleep_stress")),
            "avg_overnight_hrv": _num(night.get("avg_overnight_hrv")),
        },
        raw_payload_id=raw_id,
    )
    return 1


@handler("sleep_summary")
def sleep_summary(session: Session, result: ProviderResult, raw_id: Optional[int]) -> int:
    payload = result.data
    day = _day_of(result, payload)
    if not isinstance(payload, dict) or day is None:
        return 0
    return _write_sleep(session, day, payload, raw_id)


@handler("sleep_range")
def sleep_range(session: Session, result: ProviderResult, raw_id: Optional[int]) -> int:
    payload = result.data
    if not isinstance(payload, dict):
        return 0
    written = 0
    for night in payload.get("nights") or []:
        day = _as_date(night.get("date"))
        if day:
            written += _write_sleep(session, day, night, raw_id)
    return written


@handler("stress_summary")
def stress_summary(session: Session, result: ProviderResult, raw_id: Optional[int]) -> int:
    payload = result.data
    day = _day_of(result, payload)
    if not isinstance(payload, dict) or day is None:
        return 0
    upsert(
        session, StressRecord, {"source": SOURCE, "day": day},
        {
            "avg_stress": _score(payload.get("avg_stress_level")),
            "max_stress": _score(payload.get("max_stress_level")),
            "rest_pct": _num(payload.get("rest_percent")),
            "low_pct": _num(payload.get("low_stress_percent")),
            "medium_pct": _num(payload.get("medium_stress_percent")),
            "high_pct": _num(payload.get("high_stress_percent")),
            "data_points": _int(payload.get("data_points_count")),
        },
        raw_payload_id=raw_id,
    )
    upsert(
        session, DailyHealth, {"source": SOURCE, "day": day},
        {
            "avg_stress": _score(payload.get("avg_stress_level")),
            "max_stress": _score(payload.get("max_stress_level")),
        },
    )
    return 1


@handler("hrv_daily")
def hrv_daily(session: Session, result: ProviderResult, raw_id: Optional[int]) -> int:
    payload = result.data
    day = _day_of(result, payload)
    if not isinstance(payload, dict) or day is None:
        return 0
    upsert(
        session, HrvRecord, {"source": SOURCE, "day": day},
        {
            "last_night_avg_ms": _num(payload.get("last_night_avg_hrv_ms")),
            "last_night_5min_high_ms": _num(payload.get("last_night_5min_high_hrv_ms")),
            "weekly_avg_ms": _num(payload.get("weekly_avg_hrv_ms")),
            "baseline_low_ms": _num(payload.get("baseline_low_upper_ms")),
            "baseline_balanced_low_ms": _num(payload.get("baseline_balanced_low_ms")),
            "baseline_balanced_upper_ms": _num(payload.get("baseline_balanced_upper_ms")),
            "status": payload.get("status"),
            "feedback": payload.get("feedback"),
        },
        raw_payload_id=raw_id,
    )
    return 1


@handler("hrv_trend")
def hrv_trend(session: Session, result: ProviderResult, raw_id: Optional[int]) -> int:
    payload = result.data
    if not isinstance(payload, dict):
        return 0
    written = 0
    for entry in payload.get("trend") or payload.get("readings") or []:
        day = _as_date(entry.get("date") or entry.get("calendar_date"))
        if day is None:
            continue
        upsert(
            session, HrvRecord, {"source": SOURCE, "day": day},
            {
                "last_night_avg_ms": _num(
                    entry.get("last_night_avg_hrv_ms") or entry.get("avg_hrv_ms")
                    or entry.get("hrv_ms")
                ),
                "weekly_avg_ms": _num(entry.get("weekly_avg_hrv_ms")),
                "status": entry.get("status"),
            },
            raw_payload_id=raw_id,
        )
        written += 1
    return written


@handler("training_readiness")
def training_readiness(session: Session, result: ProviderResult, raw_id: Optional[int]) -> int:
    payload = result.data
    if isinstance(payload, list):
        payload = payload[0] if payload else None
    day = _day_of(result, payload)
    if not isinstance(payload, dict) or day is None:
        return 0
    factors = {
        key: payload.get(key)
        for key in (
            "sleep_score", "sleep_score_factor_percent", "recovery_time",
            "recovery_time_factor_percent", "hrv_factor_percent", "hrv_weekly_average",
            "acute_load", "acwr_factor_percent", "stress_history_factor_percent",
            "sleep_history_factor_percent", "feedback_long", "feedback_short",
        )
        if payload.get(key) is not None
    }
    score = _int(payload.get("score") if payload.get("score") is not None else payload.get("training_readiness_score"))
    upsert(
        session, DailyHealth, {"source": SOURCE, "day": day},
        {
            "training_readiness": score,
            "readiness_level": payload.get("level") or payload.get("feedback_short"),
            "readiness_factors": factors or None,
        },
        raw_payload_id=raw_id,
    )
    return 1


@handler("body_battery")
def body_battery(session: Session, result: ProviderResult, raw_id: Optional[int]) -> int:
    payload = result.data
    entries = payload if isinstance(payload, list) else [payload]
    written = 0
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        day = _as_date(entry.get("date")) or _requested_date(result)
        if day is None:
            continue
        events = entry.get("events") or None
        upsert(
            session, BodyBatteryRecord, {"source": SOURCE, "day": day},
            {
                "charged": _int(entry.get("charged")),
                "drained": _int(entry.get("drained")),
                "highest": _int(entry.get("highest") or entry.get("body_battery_highest")),
                "lowest": _int(entry.get("lowest") or entry.get("body_battery_lowest")),
                "level_label": entry.get("body_battery_level"),
                "feedback": entry.get("current_feedback"),
                "events": events,
            },
            raw_payload_id=raw_id,
        )
        upsert(
            session, DailyHealth, {"source": SOURCE, "day": day},
            {
                "body_battery_charged": _int(entry.get("charged")),
                "body_battery_drained": _int(entry.get("drained")),
            },
        )
        written += 1
    return written


@handler("respiration_summary")
def respiration_summary(session: Session, result: ProviderResult, raw_id: Optional[int]) -> int:
    payload = result.data
    day = _day_of(result, payload)
    if not isinstance(payload, dict) or day is None:
        return 0
    upsert(
        session, DailyHealth, {"source": SOURCE, "day": day},
        {
            "lowest_respiration": _num(payload.get("lowest_breaths_per_min")),
            "highest_respiration": _num(payload.get("highest_breaths_per_min")),
            "avg_waking_respiration": _num(payload.get("avg_waking_breaths_per_min")),
            "avg_sleep_respiration": _num(payload.get("avg_sleep_breaths_per_min")),
        },
        raw_payload_id=raw_id,
    )
    return 1


@handler("respiration_trend")
def respiration_trend(session: Session, result: ProviderResult, raw_id: Optional[int]) -> int:
    payload = result.data
    if not isinstance(payload, dict):
        return 0
    written = 0
    for entry in payload.get("trend") or []:
        day = _as_date(entry.get("date"))
        if day is None:
            continue
        upsert(
            session, DailyHealth, {"source": SOURCE, "day": day},
            {
                "avg_waking_respiration": _num(entry.get("avg_waking_breaths_per_min")),
                "avg_sleep_respiration": _num(entry.get("avg_sleep_breaths_per_min")),
            },
            raw_payload_id=raw_id,
        )
        written += 1
    return written


@handler("spo2")
def spo2(session: Session, result: ProviderResult, raw_id: Optional[int]) -> int:
    payload = result.data
    day = _day_of(result, payload)
    if not isinstance(payload, dict) or day is None:
        return 0
    average = _num(payload.get("average_spo2") or payload.get("avg_spo2"))
    lowest = _num(payload.get("lowest_spo2") or payload.get("min_spo2"))
    if average is None and lowest is None:
        return 0
    upsert(
        session, DailyHealth, {"source": SOURCE, "day": day},
        {"spo2_avg": average, "spo2_lowest": lowest},
        raw_payload_id=raw_id,
    )
    return 1


@handler("daily_steps")
def daily_steps(session: Session, result: ProviderResult, raw_id: Optional[int]) -> int:
    payload = result.data
    entries = payload if isinstance(payload, list) else (payload or {}).get("daily_data") or []
    written = 0
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        day = _as_date(entry.get("calendarDate") or entry.get("date"))
        if day is None:
            continue
        upsert(
            session, DailyHealth, {"source": SOURCE, "day": day},
            {
                "steps": _int(entry.get("totalSteps") or entry.get("total_steps")),
                "step_goal": _int(entry.get("stepGoal") or entry.get("step_goal")),
                "distance_m": _num(entry.get("totalDistance") or entry.get("distance_meters")),
            },
            raw_payload_id=raw_id,
        )
        written += 1
    return written


def _weekly(metric_prefix: str, list_key: str, fields: dict[str, str]) -> Handler:
    def run(session: Session, result: ProviderResult, raw_id: Optional[int]) -> int:
        payload = result.data
        if not isinstance(payload, dict):
            return 0
        written = 0
        for entry in payload.get(list_key) or []:
            day = _as_date(entry.get("week_start") or entry.get("calendarDate"))
            if day is None:
                continue
            for metric_suffix, source_key in fields.items():
                written += _perf(
                    session, f"{metric_prefix}_{metric_suffix}", day,
                    _num(entry.get(source_key)), raw_id=raw_id,
                )
        return written

    return run


_HANDLERS["weekly_steps"] = _weekly(
    "weekly_steps", "weekly_data",
    {"total": "total_steps", "average": "average_steps", "distance_m": "total_distance_meters"},
)
_HANDLERS["weekly_stress"] = _weekly(
    "weekly_stress", "weekly_data", {"average": "average_stress_level"}
)
_HANDLERS["weekly_intensity"] = _weekly(
    "weekly_intensity", "weekly_data",
    {"moderate": "moderate_minutes", "vigorous": "vigorous_minutes", "total": "total_minutes"},
)


@handler("body_composition")
def body_composition(session: Session, result: ProviderResult, raw_id: Optional[int]) -> int:
    payload = result.data
    if not isinstance(payload, dict):
        return 0
    written = 0
    for entry in payload.get("dateWeightList") or []:
        day = _as_date(entry.get("calendarDate"))
        if day is None:
            continue
        # Garmin reports mass in grams here.
        weight = _num(entry.get("weight"))
        upsert(
            session, BodyComposition, {"source": SOURCE, "day": day},
            {
                "weight_kg": weight / 1000 if weight else None,
                "bmi": _num(entry.get("bmi")),
                "body_fat_pct": _num(entry.get("bodyFat")),
                "body_water_pct": _num(entry.get("bodyWater")),
                "bone_mass_kg": (_num(entry.get("boneMass")) or 0) / 1000 or None,
                "muscle_mass_kg": (_num(entry.get("muscleMass")) or 0) / 1000 or None,
            },
            raw_payload_id=raw_id,
        )
        written += 1
    return written


@handler("weigh_ins")
def weigh_ins(session: Session, result: ProviderResult, raw_id: Optional[int]) -> int:
    payload = result.data
    if not isinstance(payload, dict):
        return 0
    written = 0
    for entry in payload.get("dailyWeightSummaries") or payload.get("measurements") or []:
        day = _as_date(entry.get("summaryDate") or entry.get("calendarDate"))
        weight = _num(entry.get("weight") or (entry.get("allWeightMetrics") or [{}])[0].get("weight"))
        if day is None or weight is None:
            continue
        upsert(
            session, BodyComposition, {"source": SOURCE, "day": day},
            {"weight_kg": weight / 1000},
            raw_payload_id=raw_id,
        )
        written += 1
    return written


# -- training --------------------------------------------------------------


@handler("training_status")
def training_status(session: Session, result: ProviderResult, raw_id: Optional[int]) -> int:
    payload = result.data
    day = _day_of(result, payload)
    if not isinstance(payload, dict) or day is None:
        return 0
    upsert(
        session, TrainingStatusRecord, {"source": SOURCE, "day": day},
        {
            "status_code": _int(payload.get("training_status")),
            "status_label": payload.get("training_status_feedback"),
            "feedback": payload.get("training_status_feedback"),
            "fitness_trend": _int(payload.get("fitness_trend")),
            "acwr": _num(payload.get("load_ratio")),
            "acwr_status": payload.get("acwr_status"),
            "load_aerobic_low": _num(payload.get("monthly_load_aerobic_low")),
            "load_aerobic_high": _num(payload.get("monthly_load_aerobic_high")),
            "load_anaerobic": _num(payload.get("monthly_load_anaerobic")),
            "balance_feedback": payload.get("training_balance_feedback"),
        },
        raw_payload_id=raw_id,
    )
    upsert(
        session, TrainingLoadRecord, {"source": SOURCE, "day": day},
        {
            "acute_load": _num(payload.get("acute_load")),
            "chronic_load": _num(payload.get("chronic_load")),
            "acwr": _num(payload.get("load_ratio")),
            "acwr_status": payload.get("acwr_status"),
            "optimal_min": _num(payload.get("optimal_chronic_load_min")),
            "optimal_max": _num(payload.get("optimal_chronic_load_max")),
        },
        raw_payload_id=raw_id,
    )
    return 1


@handler("training_load_trend")
def training_load_trend(session: Session, result: ProviderResult, raw_id: Optional[int]) -> int:
    payload = result.data
    if not isinstance(payload, dict):
        return 0
    written = 0
    for entry in payload.get("trend") or []:
        day = _as_date(entry.get("date"))
        if day is None:
            continue
        upsert(
            session, TrainingLoadRecord, {"source": SOURCE, "day": day},
            {
                "acute_load": _num(entry.get("atl")),
                "chronic_load": _num(entry.get("ctl")),
                "balance": _num(entry.get("tsb")),
                "acwr": _num(entry.get("acwr")),
                "acwr_status": entry.get("acwr_status"),
                "optimal_min": _num(entry.get("optimal_chronic_load_min")),
                "optimal_max": _num(entry.get("optimal_chronic_load_max")),
                "training_status": entry.get("training_status"),
                "vo2max": _num(entry.get("vo2_max")),
            },
            raw_payload_id=raw_id,
        )
        written += 1
    return written


@handler("training_load_balance")
def training_load_balance(session: Session, result: ProviderResult, raw_id: Optional[int]) -> int:
    payload = result.data
    day = _day_of(result, payload)
    if not isinstance(payload, dict) or day is None:
        return 0
    upsert(
        session, TrainingStatusRecord, {"source": SOURCE, "day": day},
        {
            "load_aerobic_low": _num((payload.get("aerobic_low") or {}).get("load")),
            "load_aerobic_high": _num((payload.get("aerobic_high") or {}).get("load")),
            "load_anaerobic": _num((payload.get("anaerobic") or {}).get("load")),
            "balance_feedback": payload.get("feedback"),
        },
        raw_payload_id=raw_id,
    )
    return 1


@handler("vo2max_trend")
def vo2max_trend(session: Session, result: ProviderResult, raw_id: Optional[int]) -> int:
    payload = result.data
    if not isinstance(payload, dict):
        return 0
    sport = payload.get("sport") or "generic"
    written = 0
    for entry in payload.get("trend") or []:
        written += _perf(
            session, "vo2max", _as_date(entry.get("date")), _num(entry.get("vo2_max")),
            sport=str(sport), units="ml/kg/min",
            context={"provider_source": entry.get("source")}, raw_id=raw_id,
        )
    return written


@handler("running_tolerance")
def running_tolerance(session: Session, result: ProviderResult, raw_id: Optional[int]) -> int:
    payload = result.data
    day = _day_of(result, payload)
    if not isinstance(payload, dict) or day is None:
        return 0
    written = 0
    for metric, key in (
        ("running_tolerance", "running_tolerance"),
        ("running_tolerance_weekly_load", "weekly_load"),
        ("running_tolerance_acute_load", "acute_load"),
    ):
        written += _perf(session, metric, day, _num(payload.get(key)), sport="run",
                         raw_id=raw_id)
    return written


@handler("running_tolerance_trend")
def running_tolerance_trend(session: Session, result: ProviderResult, raw_id: Optional[int]) -> int:
    payload = result.data
    if not isinstance(payload, dict):
        return 0
    written = 0
    for entry in payload.get("trend") or payload.get("data") or []:
        written += _perf(
            session, "running_tolerance",
            _as_date(entry.get("date") or entry.get("week_start")),
            _num(entry.get("running_tolerance") or entry.get("value")),
            sport="run", raw_id=raw_id,
        )
    return written


@handler("acclimation")
def acclimation(session: Session, result: ProviderResult, raw_id: Optional[int]) -> int:
    payload = result.data
    day = _day_of(result, payload)
    if not isinstance(payload, dict) or day is None:
        return 0
    written = 0
    written += _perf(session, "heat_acclimation", day,
                     _num(payload.get("heat_acclimation_percent")), units="%", raw_id=raw_id)
    written += _perf(session, "altitude_acclimation", day,
                     _num(payload.get("altitude_acclimation_percent")
                          or payload.get("altitude_acclimation")), units="%", raw_id=raw_id)
    return written


@handler("lactate_threshold")
def lactate_threshold(session: Session, result: ProviderResult, raw_id: Optional[int]) -> int:
    payload = result.data
    if not isinstance(payload, dict):
        return 0
    day = _as_date(payload.get("speed_hr_date")) or _requested_date(result) or date.today()
    written = 0
    written += _perf(session, "lactate_threshold_hr", day,
                     _num(payload.get("lactate_threshold_heart_rate_bpm")), units="bpm",
                     raw_id=raw_id)
    written += _perf(session, "lactate_threshold_speed", day,
                     _num(payload.get("lactate_threshold_speed_mps")), units="m/s",
                     raw_id=raw_id)
    power_day = _as_date(payload.get("power_date")) or day
    written += _perf(session, "ftp", power_day,
                     _num(payload.get("functional_threshold_power_watts")), sport="ride",
                     units="W", raw_id=raw_id)
    written += _perf(session, "power_to_weight", power_day,
                     _num(payload.get("power_to_weight")), sport="ride", units="W/kg",
                     raw_id=raw_id)
    athlete_weight = _num(payload.get("weight_kg"))
    if athlete_weight:
        upsert(session, Athlete, {"source": SOURCE, "provider_id": "self"},
               {"weight_kg": athlete_weight})
    return written


@handler("cycling_ftp")
def cycling_ftp(session: Session, result: ProviderResult, raw_id: Optional[int]) -> int:
    payload = result.data
    if not isinstance(payload, dict):
        return 0
    day = _as_date(payload.get("calendar_date")) or _requested_date(result) or date.today()
    return _perf(session, "ftp", day,
                 _num(payload.get("functional_threshold_power_watts")), sport="ride",
                 units="W", context={"is_stale": payload.get("is_stale")}, raw_id=raw_id)


@handler("race_predictions")
def race_predictions(session: Session, result: ProviderResult, raw_id: Optional[int]) -> int:
    payload = result.data
    if not isinstance(payload, dict):
        return 0
    day = _as_date(payload.get("prediction_date")) or date.today()
    written = 0
    for label, entry in (payload.get("predictions") or {}).items():
        if not isinstance(entry, dict):
            continue
        written += _perf(
            session, f"race_prediction_{label.lower()}", day,
            _num(entry.get("time_seconds")), sport="run", units="s",
            text_value=entry.get("time"), raw_id=raw_id,
        )
    return written


@handler("endurance_score")
def endurance_score(session: Session, result: ProviderResult, raw_id: Optional[int]) -> int:
    payload = result.data
    if not isinstance(payload, dict):
        return 0
    written = 0
    entries = payload.get("daily_scores") or payload.get("scores") or []
    for entry in entries:
        written += _perf(session, "endurance_score", _as_date(entry.get("date")),
                         _num(entry.get("score") or entry.get("overall_score")),
                         raw_id=raw_id)
    if not written and payload.get("overall_score") is not None:
        written += _perf(session, "endurance_score", _requested_date(result),
                         _num(payload.get("overall_score")), raw_id=raw_id)
    return written


@handler("hill_score")
def hill_score(session: Session, result: ProviderResult, raw_id: Optional[int]) -> int:
    payload = result.data
    if not isinstance(payload, dict):
        return 0
    written = 0
    for entry in payload.get("daily_scores") or []:
        written += _perf(session, "hill_score", _as_date(entry.get("date")),
                         _num(entry.get("overall_score") or entry.get("score")),
                         raw_id=raw_id)
    return written


@handler("fitness_age")
def fitness_age(session: Session, result: ProviderResult, raw_id: Optional[int]) -> int:
    payload = result.data
    day = _day_of(result, payload)
    if not isinstance(payload, dict) or day is None:
        return 0
    return _perf(session, "fitness_age", day,
                 _num(payload.get("fitness_age") or payload.get("fitnessAge")),
                 units="years", raw_id=raw_id)


@handler("progress_summary")
def progress_summary(session: Session, result: ProviderResult, raw_id: Optional[int]) -> int:
    """Stored as raw only — the shape varies by requested metric."""
    return 0


@handler("calendar_events")
def calendar_events(session: Session, result: ProviderResult, raw_id: Optional[int]) -> int:
    return 0


# -- account ---------------------------------------------------------------


@handler("user_profile")
def user_profile(session: Session, result: ProviderResult, raw_id: Optional[int]) -> int:
    payload = result.data
    if not isinstance(payload, dict):
        return 0
    user = payload.get("userData") or {}
    height = _num(user.get("height"))
    upsert(
        session, Athlete, {"source": SOURCE, "provider_id": str(payload.get("id", "self"))},
        {
            "display_name": payload.get("fullName") or payload.get("displayName"),
            "sex": user.get("gender"),
            "birth_date": _as_date(user.get("birthDate")),
            "height_cm": height,
            "weight_kg": (_num(user.get("weight")) or 0) / 1000 or None,
            "measurement_system": user.get("measurementSystem"),
            "vo2max_running": _num(user.get("vo2MaxRunning")),
            "vo2max_cycling": _num(user.get("vo2MaxCycling")),
            "lactate_threshold_hr": _int(user.get("lactateThresholdHeartRate")),
            "lactate_threshold_speed_mps": _num(user.get("lactateThresholdSpeed")),
        },
        raw_payload_id=raw_id,
    )
    return 1


@handler("unit_system")
def unit_system(session: Session, result: ProviderResult, raw_id: Optional[int]) -> int:
    return 0


@handler("hr_zones")
def hr_zones(session: Session, result: ProviderResult, raw_id: Optional[int]) -> int:
    payload = result.data
    entries = payload if isinstance(payload, list) else [payload]
    written = 0
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        floors = [
            _int(entry.get(f"zone{n}Floor")) for n in range(1, 6)
        ]
        upsert(
            session, HeartRateZoneSet,
            {"source": SOURCE, "sport": str(entry.get("sport") or "default").lower()},
            {
                "method": entry.get("trainingMethod"),
                "resting_hr": _int(entry.get("restingHeartRateUsed")),
                "max_hr": _int(entry.get("maxHeartRateUsed")),
                "lactate_threshold_hr": _int(entry.get("lactateThresholdHeartRateUsed")),
                "zone_floors": floors,
            },
        )
        written += 1
    return written


@handler("devices")
def devices(session: Session, result: ProviderResult, raw_id: Optional[int]) -> int:
    payload = result.data
    if not isinstance(payload, list):
        return 0
    written = 0
    for entry in payload:
        if not isinstance(entry, dict) or entry.get("device_id") is None:
            continue
        upsert(
            session, Device,
            {"source": SOURCE, "provider_id": str(entry["device_id"])},
            {
                "name": entry.get("device_name"),
                "model": entry.get("model"),
                # Serial numbers identify hardware; kept for device matching but
                # never surfaced by the API.
                "serial_number": str(entry.get("serial_number") or "") or None,
            },
        )
        written += 1
    return written


@handler("device_last_used")
def device_last_used(session: Session, result: ProviderResult, raw_id: Optional[int]) -> int:
    payload = result.data
    if not isinstance(payload, dict) or payload.get("user_device_id") is None:
        return 0
    upsert(
        session, Device,
        {"source": SOURCE, "provider_id": str(payload["user_device_id"])},
        {
            "name": payload.get("device_name"),
            "last_used_at": _dt(payload.get("last_upload_time")),
        },
    )
    return 1


@handler("primary_training_device")
def primary_training_device(session: Session, result: ProviderResult, raw_id: Optional[int]) -> int:
    payload = result.data
    if not isinstance(payload, dict):
        return 0
    primary = payload.get("primary_device_id")
    written = 0
    for entry in payload.get("training_devices") or []:
        device_id = entry.get("device_id")
        if device_id is None:
            continue
        upsert(
            session, Device, {"source": SOURCE, "provider_id": str(device_id)},
            {
                "name": entry.get("display_name"),
                "is_primary": bool(primary is not None and device_id == primary),
                "details": {
                    "primary_training_capable": entry.get("primary_training_capable"),
                    "is_primary_wearable": entry.get("is_primary_wearable"),
                },
            },
        )
        written += 1
    return written


@handler("gear")
def gear(session: Session, result: ProviderResult, raw_id: Optional[int]) -> int:
    payload = result.data
    entries = payload if isinstance(payload, list) else (payload or {}).get("gear") or []
    written = 0
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        gear_id = entry.get("uuid") or entry.get("gearPk") or entry.get("id")
        if gear_id is None:
            continue
        upsert(
            session, Gear, {"source": SOURCE, "provider_id": str(gear_id)},
            {
                "name": entry.get("displayName") or entry.get("customMakeModel")
                or entry.get("name"),
                "brand": entry.get("gearMakeName") or entry.get("brand"),
                "model": entry.get("gearModelName") or entry.get("model"),
                "gear_type": entry.get("gearTypeName") or entry.get("gear_type"),
                "retired": bool(entry.get("gearStatusName") == "retired"
                                or entry.get("retired")),
                "provider_distance_m": _num(entry.get("totalDistance")
                                            or entry.get("total_distance_meters")),
            },
        )
        written += 1
    return written


@handler("personal_records")
def personal_records(session: Session, result: ProviderResult, raw_id: Optional[int]) -> int:
    payload = result.data
    if not isinstance(payload, list):
        return 0
    written = 0
    for entry in payload:
        if not isinstance(entry, dict):
            continue
        reported = _as_date(entry.get("date"))
        # Garmin frequently returns a null date for a record. Store the row under
        # today so it is still queryable, but mark the date as unknown so the API
        # can report "not reported" instead of inventing the day it was set.
        day = reported or date.today()
        record_type = str(entry.get("record_type") or entry.get("type_id") or "unknown")
        written += _perf(
            session, f"pr:{record_type}", day, _num(entry.get("raw_value")),
            text_value=entry.get("value"),
            context={
                "activity_id": str(entry["activity_id"]) if entry.get("activity_id") else None,
                "date_known": reported is not None,
            },
            raw_id=raw_id,
        )
    return written
