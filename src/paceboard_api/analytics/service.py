"""Compute derived metrics from stored data and answer analytics queries.

Two shapes of output:

* :class:`MetricValue` — a computed number *or* a stated reason it is
  unavailable. The API returns these verbatim so the UI can render
  "Unavailable — no HR zones recorded" instead of an empty chart.
* persisted :class:`~paceboard_api.db.models.DerivedMetric` rows, which record
  the formula version, input sources, units and calculation time.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any, Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..db.models import (
    Activity,
    ActivityZone,
    Athlete,
    BodyBatteryRecord,
    DailyHealth,
    DerivedMetric,
    Gear,
    HeartRateZoneSet,
    HrvRecord,
    PerformanceMetric,
    SleepRecord,
    StressRecord,
    TrainingLoadRecord,
)
from ..ingest.activities import load_streams
from ..logging_conf import get_logger
from . import formulas as F

log = get_logger("paceboard.analytics")

CTL_DAYS = 42.0
ATL_DAYS = 7.0
HRV_BASELINE_DAYS = 7
RHR_BASELINE_DAYS = 28

POWER_DURATIONS = (5, 15, 30, 60, 300, 600, 1200, 1800, 3600)
PACE_DURATIONS = (60, 300, 600, 1200, 1800, 3600)
EFFORT_DISTANCES = (400.0, 1000.0, 1609.34, 5000.0, 10000.0, 21097.5, 42195.0)


@dataclass
class MetricValue:
    """A derived value, or an explicit reason it could not be computed."""

    value: Optional[float] = None
    units: Optional[str] = None
    unavailable_reason: Optional[str] = None
    inputs: list[str] = field(default_factory=list)
    formula_version: str = F.FORMULA_VERSION
    detail: dict[str, Any] = field(default_factory=dict)

    @property
    def available(self) -> bool:
        return self.value is not None

    def as_dict(self) -> dict[str, Any]:
        return {
            "value": self.value,
            "units": self.units,
            "available": self.available,
            "unavailable_reason": self.unavailable_reason,
            "inputs": self.inputs,
            "formula_version": self.formula_version,
            "detail": self.detail or None,
        }


def unavailable(reason: str, units: Optional[str] = None) -> MetricValue:
    return MetricValue(unavailable_reason=reason, units=units)


# -- persistence -----------------------------------------------------------


def store_metric(
    session: Session,
    metric: str,
    scope: str,
    scope_key: str,
    value: MetricValue,
) -> Optional[DerivedMetric]:
    if not value.available:
        return None
    row = session.execute(
        select(DerivedMetric).where(
            DerivedMetric.metric == metric,
            DerivedMetric.scope == scope,
            DerivedMetric.scope_key == scope_key,
        )
    ).scalar_one_or_none()
    if row is None:
        row = DerivedMetric(metric=metric, scope=scope, scope_key=scope_key)
        session.add(row)
    row.value = value.value
    row.units = value.units
    row.formula_version = value.formula_version
    row.input_sources = value.inputs
    row.detail = value.detail or None
    row.calculated_at = datetime.utcnow()
    session.flush()
    return row


# -- helpers ---------------------------------------------------------------


def _athlete(session: Session) -> Optional[Athlete]:
    return session.execute(
        select(Athlete).order_by(Athlete.source.desc())
    ).scalars().first()


def _max_hr(session: Session) -> Optional[int]:
    zones = session.execute(
        select(HeartRateZoneSet).order_by(HeartRateZoneSet.sport)
    ).scalars().all()
    values = [z.max_hr for z in zones if z.max_hr]
    if values:
        return max(values)
    observed = session.execute(select(func.max(DailyHealth.max_hr))).scalar()
    return int(observed) if observed else None


def _resting_hr(session: Session, day: Optional[date] = None) -> Optional[int]:
    stmt = select(DailyHealth.resting_hr).where(DailyHealth.resting_hr.isnot(None))
    if day:
        stmt = stmt.where(DailyHealth.day <= day)
    return session.execute(stmt.order_by(DailyHealth.day.desc()).limit(1)).scalar()


def _ftp(session: Session) -> Optional[float]:
    return session.execute(
        select(PerformanceMetric.value)
        .where(PerformanceMetric.metric == "ftp")
        .order_by(PerformanceMetric.day.desc())
        .limit(1)
    ).scalar()


def date_series(start: date, end: date) -> list[date]:
    return [start + timedelta(days=i) for i in range((end - start).days + 1)]


# -- activity-level --------------------------------------------------------


def activity_trimp(session: Session, activity: Activity) -> MetricValue:
    max_hr = _max_hr(session)
    resting = _resting_hr(session, activity.local_date)
    athlete = _athlete(session)
    if activity.avg_hr is None:
        return unavailable("No average heart rate recorded for this activity", "au")
    if max_hr is None or resting is None:
        return unavailable(
            "Needs maximum and resting heart rate — sync heart-rate zones and "
            "daily health first",
            "au",
        )
    minutes = (activity.moving_duration_s or activity.duration_s or 0) / 60
    value = F.trimp_banister(minutes, activity.avg_hr, resting, max_hr,
                             athlete.sex if athlete else None)
    if value is None:
        return unavailable("Heart-rate reserve could not be computed", "au")
    return MetricValue(
        value=round(value, 1), units="au",
        inputs=["activity.avg_hr", "daily_health.resting_hr", "heart_rate_zones.max_hr"],
        detail={"max_hr": max_hr, "resting_hr": resting,
                "sex_constant": "female" if (athlete and (athlete.sex or "").lower()
                                             .startswith("f")) else "male"},
    )


def activity_stream_metrics(session: Session, activity: Activity) -> dict[str, MetricValue]:
    """Decoupling, NP/IF/TSS, best efforts and curves for one activity."""
    streams = load_streams(session, activity.id)
    out: dict[str, MetricValue] = {}
    sample_seconds = _sample_interval(streams)

    watts = streams.get("watts", {}).get("data") or []
    heartrate = streams.get("heartrate", {}).get("data") or []
    speed = streams.get("velocity_smooth", {}).get("data") or []
    distance = streams.get("distance", {}).get("data") or []
    elapsed = streams.get("time", {}).get("data") or []

    if watts:
        np_value = F.normalized_power(watts, sample_seconds)
        out["normalized_power"] = (
            MetricValue(round(np_value, 1), "W", inputs=["streams.watts"])
            if np_value is not None
            else unavailable("Fewer than 30 seconds of power data", "W")
        )
        ftp = _ftp(session)
        if np_value is not None and ftp:
            out["intensity_factor"] = MetricValue(
                round(F.intensity_factor(np_value, ftp) or 0, 3), "ratio",
                inputs=["streams.watts", "performance_metrics.ftp"],
            )
            tss = F.training_stress_score(
                activity.moving_duration_s or activity.duration_s, np_value, ftp
            )
            out["training_stress_score"] = (
                MetricValue(round(tss, 1), "TSS",
                            inputs=["streams.watts", "performance_metrics.ftp"])
                if tss is not None else unavailable("Duration missing", "TSS")
            )
        else:
            out["intensity_factor"] = unavailable(
                "No FTP recorded — sync training metrics or set one in Garmin", "ratio"
            )
        athlete = _athlete(session)
        wkg = F.watts_per_kg(activity.avg_power_w, athlete.weight_kg if athlete else None)
        out["watts_per_kg"] = (
            MetricValue(round(wkg, 2), "W/kg",
                        inputs=["activity.avg_power_w", "athlete.weight_kg"])
            if wkg is not None
            else unavailable("Needs average power and a recorded body weight", "W/kg")
        )
    else:
        out["normalized_power"] = unavailable("No power data in this activity", "W")

    if heartrate and (speed or watts):
        output = watts if watts else speed
        drift = F.aerobic_decoupling(output, heartrate)
        out["aerobic_decoupling"] = (
            MetricValue(
                round(drift, 2), "%",
                inputs=["streams.heartrate", "streams.watts" if watts else "streams.velocity_smooth"],
                detail={"basis": "power" if watts else "speed"},
            )
            if drift is not None
            else unavailable("Fewer than 20 paired heart-rate samples", "%")
        )
    else:
        out["aerobic_decoupling"] = unavailable(
            "Needs heart rate plus power or speed samples", "%"
        )

    if speed:
        curve = F.best_average_curve(speed, PACE_DURATIONS, sample_seconds)
        out["pace_curve"] = MetricValue(
            value=float(len(curve)), units="m/s", inputs=["streams.velocity_smooth"],
            detail={"points": {str(k): round(v, 3) for k, v in curve.items()}},
        )
    if watts:
        curve = F.best_average_curve(watts, POWER_DURATIONS, sample_seconds)
        out["power_curve"] = MetricValue(
            value=float(len(curve)), units="W", inputs=["streams.watts"],
            detail={"points": {str(k): round(v, 1) for k, v in curve.items()}},
        )
    if distance and elapsed:
        efforts = F.best_efforts(distance, elapsed, EFFORT_DISTANCES)
        out["best_efforts"] = MetricValue(
            value=float(len(efforts)), units="s",
            inputs=["streams.distance", "streams.time"],
            detail={"points": {str(int(k)): round(v, 1) for k, v in efforts.items()}},
        )
    return out


def _sample_interval(streams: dict[str, dict[str, Any]]) -> float:
    times = streams.get("time", {}).get("data") or []
    clean = [t for t in times if t is not None]
    if len(clean) < 2:
        return 1.0
    span = clean[-1] - clean[0]
    return max(span / (len(clean) - 1), 0.1) if span > 0 else 1.0


# -- training load ---------------------------------------------------------


def load_series(
    session: Session, start: date, end: date
) -> dict[str, list[Optional[float]]]:
    """Paceboard's own CTL/ATL/TSB alongside Garmin's reported values.

    Paceboard's series is computed from per-activity TRIMP so it exists even for
    days Garmin has no PMC entry for; Garmin's is passed through unchanged. The
    two are returned side by side rather than blended, because they use different
    load units and mixing them would be meaningless.
    """
    days = date_series(start, end)
    index = {day: i for i, day in enumerate(days)}

    daily_trimp = [0.0] * len(days)
    activities = session.execute(
        select(Activity).where(
            Activity.start_time_utc >= datetime.combine(start, datetime.min.time()),
            Activity.start_time_utc <= datetime.combine(end, datetime.max.time()),
        )
    ).scalars().all()
    max_hr = _max_hr(session)
    athlete = _athlete(session)
    for activity in activities:
        day = activity.local_date or activity.start_time_utc.date()
        if day not in index:
            continue
        resting = _resting_hr(session, day)
        minutes = (activity.moving_duration_s or activity.duration_s or 0) / 60
        value = F.trimp_banister(minutes, activity.avg_hr, resting, max_hr,
                                 athlete.sex if athlete else None)
        if value is None and activity.training_load:
            value = float(activity.training_load)
        if value:
            daily_trimp[index[day]] += value

    ctl = F.exponential_load(daily_trimp, CTL_DAYS)
    atl = F.exponential_load(daily_trimp, ATL_DAYS)
    tsb = [F.training_stress_balance(c, a) for c, a in zip(ctl, atl)]

    provider_rows = {
        row.day: row
        for row in session.execute(
            select(TrainingLoadRecord).where(
                TrainingLoadRecord.day >= start, TrainingLoadRecord.day <= end
            )
        ).scalars()
    }
    return {
        "days": [d.isoformat() for d in days],
        "daily_load": [round(v, 1) for v in daily_trimp],
        "ctl": [round(v, 2) for v in ctl],
        "atl": [round(v, 2) for v in atl],
        "tsb": [round(v, 2) for v in tsb],
        "garmin_acute": [
            provider_rows[d].acute_load if d in provider_rows else None for d in days
        ],
        "garmin_chronic": [
            provider_rows[d].chronic_load if d in provider_rows else None for d in days
        ],
        "garmin_acwr": [
            provider_rows[d].acwr if d in provider_rows else None for d in days
        ],
    }


def weekly_volume(
    session: Session, start: date, end: date
) -> list[dict[str, Any]]:
    """Distance / duration / elevation / count per ISO week, split by sport."""
    activities = session.execute(
        select(Activity).where(
            Activity.start_time_utc >= datetime.combine(start, datetime.min.time()),
            Activity.start_time_utc <= datetime.combine(end, datetime.max.time()),
        )
    ).scalars().all()
    buckets: dict[tuple[str, str], dict[str, float]] = defaultdict(
        lambda: {"distance_m": 0.0, "duration_s": 0.0, "elevation_m": 0.0, "count": 0}
    )
    for activity in activities:
        day = activity.local_date or activity.start_time_utc.date()
        week_start = day - timedelta(days=day.weekday())
        bucket = buckets[(week_start.isoformat(), activity.sport)]
        bucket["distance_m"] += activity.distance_m or 0
        bucket["duration_s"] += activity.moving_duration_s or activity.duration_s or 0
        bucket["elevation_m"] += activity.elevation_gain_m or 0
        bucket["count"] += 1
    return [
        {"week_start": week, "sport": sport, **values}
        for (week, sport), values in sorted(buckets.items())
    ]


def rolling_totals(session: Session, window_days: int, end: Optional[date] = None) -> dict[str, float]:
    end = end or date.today()
    start = end - timedelta(days=window_days - 1)
    row = session.execute(
        select(
            func.count(Activity.id),
            func.sum(Activity.distance_m),
            func.sum(func.coalesce(Activity.moving_duration_s, Activity.duration_s)),
            func.sum(Activity.elevation_gain_m),
        ).where(
            Activity.start_time_utc >= datetime.combine(start, datetime.min.time()),
            Activity.start_time_utc <= datetime.combine(end, datetime.max.time()),
        )
    ).one()
    return {
        "days": window_days,
        "count": row[0] or 0,
        "distance_m": float(row[1] or 0),
        "duration_s": float(row[2] or 0),
        "elevation_m": float(row[3] or 0),
    }


def monotony_and_strain(session: Session, end: Optional[date] = None) -> dict[str, MetricValue]:
    end = end or date.today()
    start = end - timedelta(days=6)
    series = load_series(session, start, end)
    loads = series["daily_load"]
    monotony_value = F.monotony(loads)
    weekly = sum(loads)
    if monotony_value is None:
        reason = "Needs at least three days of training load in the last week"
        return {"monotony": unavailable(reason, "ratio"),
                "strain": unavailable(reason, "au"),
                "weekly_load": MetricValue(round(weekly, 1), "au",
                                           inputs=["derived.daily_load"])}
    return {
        "monotony": MetricValue(round(monotony_value, 2), "ratio",
                                inputs=["derived.daily_load"]),
        "strain": MetricValue(round(F.strain(weekly, monotony_value) or 0, 1), "au",
                              inputs=["derived.daily_load"]),
        "weekly_load": MetricValue(round(weekly, 1), "au", inputs=["derived.daily_load"]),
    }


def zone_totals(
    session: Session, start: date, end: date, kind: str = "hr"
) -> dict[str, Any]:
    """Total seconds per zone across a window, for heart rate or power."""
    rows = session.execute(
        select(ActivityZone.zone_number, func.sum(ActivityZone.seconds_in_zone))
        .join(Activity, ActivityZone.activity_id == Activity.id)
        .where(
            ActivityZone.zone_kind == kind,
            Activity.start_time_utc >= datetime.combine(start, datetime.min.time()),
            Activity.start_time_utc <= datetime.combine(end, datetime.max.time()),
        )
        .group_by(ActivityZone.zone_number)
    ).all()
    seconds = {int(zone): float(total or 0) for zone, total in rows if zone}
    label = "heart-rate" if kind == "hr" else kind
    if not seconds:
        return {
            "kind": kind,
            "available": False,
            "unavailable_reason": f"No {label} zone data recorded for this window",
            "zones": {}, "distribution": None,
        }
    return {
        "kind": kind,
        "available": True,
        "unavailable_reason": None,
        "zones": seconds,
        "percent": F.zone_distribution(seconds),
        # The easy/moderate/hard split is defined against heart-rate zones; it is
        # not meaningful for power, so it is only reported for HR.
        "distribution": F.intensity_distribution(seconds) if kind == "hr" else None,
    }


# -- recovery --------------------------------------------------------------


def recovery_series(session: Session, start: date, end: date) -> dict[str, Any]:
    days = date_series(start, end)
    health = {
        row.day: row
        for row in session.execute(
            select(DailyHealth).where(DailyHealth.day >= start, DailyHealth.day <= end)
        ).scalars()
    }
    sleep = {
        row.day: row
        for row in session.execute(
            select(SleepRecord).where(SleepRecord.day >= start, SleepRecord.day <= end)
        ).scalars()
    }
    hrv = {
        row.day: row
        for row in session.execute(
            select(HrvRecord).where(HrvRecord.day >= start, HrvRecord.day <= end)
        ).scalars()
    }
    stress = {
        row.day: row
        for row in session.execute(
            select(StressRecord).where(StressRecord.day >= start, StressRecord.day <= end)
        ).scalars()
    }
    battery = {
        row.day: row
        for row in session.execute(
            select(BodyBatteryRecord).where(
                BodyBatteryRecord.day >= start, BodyBatteryRecord.day <= end
            )
        ).scalars()
    }

    hrv_values = [hrv[d].last_night_avg_ms if d in hrv else None for d in days]
    rhr_values = [health[d].resting_hr if d in health else None for d in days]
    sleep_seconds = [sleep[d].total_sleep_s if d in sleep else None for d in days]

    def pick(day: date, *candidates: Any) -> Any:
        """First non-null across sources — a present row with a null field must
        not shadow another source that does carry the value."""
        for value in candidates:
            if value is not None:
                return value
        return None

    return {
        "days": [d.isoformat() for d in days],
        "sleep_seconds": sleep_seconds,
        "sleep_score": [sleep[d].sleep_score if d in sleep else None for d in days],
        "sleep_stages": [
            {
                "deep": sleep[d].deep_s, "light": sleep[d].light_s,
                "rem": sleep[d].rem_s, "awake": sleep[d].awake_s,
            }
            if d in sleep else None
            for d in days
        ],
        "hrv_ms": hrv_values,
        "hrv_baseline": F.rolling_baseline(hrv_values, HRV_BASELINE_DAYS),
        "resting_hr": rhr_values,
        "resting_hr_baseline": F.rolling_baseline(rhr_values, RHR_BASELINE_DAYS),
        "avg_stress": [stress[d].avg_stress if d in stress else None for d in days],
        "stress_distribution": [
            {
                "rest": stress[d].rest_pct, "low": stress[d].low_pct,
                "medium": stress[d].medium_pct, "high": stress[d].high_pct,
            }
            if d in stress else None
            for d in days
        ],
        "body_battery_high": [
            pick(d,
                 battery[d].highest if d in battery else None,
                 health[d].body_battery_high if d in health else None)
            for d in days
        ],
        "body_battery_low": [
            pick(d,
                 battery[d].lowest if d in battery else None,
                 health[d].body_battery_low if d in health else None)
            for d in days
        ],
        "body_battery_charged": [
            battery[d].charged if d in battery else None for d in days
        ],
        "body_battery_drained": [
            battery[d].drained if d in battery else None for d in days
        ],
        "respiration": [
            health[d].avg_waking_respiration if d in health else None for d in days
        ],
        "spo2": [health[d].spo2_avg if d in health else None for d in days],
        "training_readiness": [
            health[d].training_readiness if d in health else None for d in days
        ],
    }


def recovery_summary(session: Session, end: Optional[date] = None) -> dict[str, Any]:
    end = end or date.today()
    start = end - timedelta(days=59)
    series = recovery_series(session, start, end)
    sleep_seconds = series["sleep_seconds"]
    hrv_values = series["hrv_ms"]

    latest_hrv = next((v for v in reversed(hrv_values) if v is not None), None)
    baseline = next((v for v in reversed(series["hrv_baseline"]) if v is not None), None)
    hrv_deviation = F.deviation_from_baseline(latest_hrv, baseline)

    bed_times: list[Optional[float]] = []
    for row in session.execute(
        select(SleepRecord).where(SleepRecord.day >= end - timedelta(days=13), SleepRecord.day <= end)
    ).scalars():
        if row.sleep_start_utc:
            seconds = (
                row.sleep_start_utc.hour * 3600
                + row.sleep_start_utc.minute * 60
                + row.sleep_start_utc.second
            )
            # Fold the evening onto a continuous axis so 23:30 and 00:30 are
            # 60 minutes apart rather than 23 hours.
            bed_times.append(seconds - 86400 if seconds > 43200 else seconds)

    debt = F.sleep_debt(sleep_seconds[-7:])
    consistency = F.sleep_consistency(bed_times)
    spread = F.bedtime_spread_minutes(bed_times)

    return {
        "range": {"start": start.isoformat(), "end": end.isoformat()},
        "hrv_latest": MetricValue(latest_hrv, "ms", inputs=["hrv_records"]).as_dict()
        if latest_hrv is not None
        else unavailable("No HRV recorded in the last 60 days", "ms").as_dict(),
        "hrv_baseline": MetricValue(
            round(baseline, 1) if baseline else None, "ms",
            inputs=["hrv_records"], detail={"window_days": HRV_BASELINE_DAYS},
        ).as_dict()
        if baseline
        else unavailable(
            f"Needs {HRV_BASELINE_DAYS} nights of HRV to establish a baseline", "ms"
        ).as_dict(),
        "hrv_deviation": MetricValue(
            round(hrv_deviation, 1) if hrv_deviation is not None else None, "%",
            inputs=["hrv_records"],
        ).as_dict()
        if hrv_deviation is not None
        else unavailable("Needs both a current HRV value and a baseline", "%").as_dict(),
        "sleep_debt_7d": MetricValue(
            round(debt, 2) if debt is not None else None, "h",
            inputs=["sleep_records"], detail={"target_hours": 8.0},
        ).as_dict()
        if debt is not None
        else unavailable("No sleep records in the last 7 days", "h").as_dict(),
        "sleep_consistency_14d": MetricValue(
            round(consistency, 1) if consistency is not None else None, "score",
            inputs=["sleep_records.sleep_start_utc"],
            detail={
                "bedtime_spread_minutes": round(spread, 1) if spread is not None else None,
                "nights": len(bed_times),
                "zero_at_spread_minutes": F.CONSISTENCY_FLOOR_MINUTES,
            },
        ).as_dict()
        if consistency is not None
        else unavailable("Needs at least 3 nights with a recorded bedtime", "score").as_dict(),
    }


def correlations(session: Session, end: Optional[date] = None, window_days: int = 90) -> list[dict[str, Any]]:
    """Recovery-versus-load correlations, reported with n and a caveat.

    These are observational associations over a single athlete's history, not
    causal claims; the API returns the sample size so the UI can say so.
    """
    end = end or date.today()
    start = end - timedelta(days=window_days - 1)
    recovery = recovery_series(session, start, end)
    load = load_series(session, start, end)

    pairs = [
        ("sleep_seconds", "next_day_readiness", recovery["sleep_seconds"],
         recovery["training_readiness"][1:] + [None]),
        ("daily_load", "next_day_hrv", load["daily_load"], recovery["hrv_ms"][1:] + [None]),
        ("daily_load", "next_day_resting_hr", load["daily_load"],
         recovery["resting_hr"][1:] + [None]),
        ("avg_stress", "sleep_score", recovery["avg_stress"], recovery["sleep_score"]),
        ("body_battery_high", "training_readiness", recovery["body_battery_high"],
         recovery["training_readiness"]),
    ]
    out: list[dict[str, Any]] = []
    for left, right, xs, ys in pairs:
        computed = F.pearson(xs, ys)
        if computed is None:
            out.append({
                "x": left, "y": right, "r": None, "n": 0, "available": False,
                "unavailable_reason": "Fewer than 5 days where both values exist",
            })
            continue
        r, n = computed
        out.append({
            "x": left, "y": right, "r": round(r, 3), "n": n, "available": True,
            "unavailable_reason": None,
            "note": "Observational association for one athlete; not causal.",
        })
    return out


# -- consistency & gear ----------------------------------------------------


def consistency(session: Session, end: Optional[date] = None, window_days: int = 90) -> dict[str, Any]:
    end = end or date.today()
    start = end - timedelta(days=window_days - 1)
    active_days = {
        (row.local_date or row.start_time_utc.date())
        for row in session.execute(
            select(Activity).where(
                Activity.start_time_utc >= datetime.combine(start, datetime.min.time())
            )
        ).scalars()
    }
    flags = [day in active_days for day in date_series(start, end)]
    current, longest = F.streaks(flags)
    return {
        "window_days": window_days,
        "active_days": sum(flags),
        "active_ratio": round(sum(flags) / len(flags), 3) if flags else 0.0,
        "current_streak": current,
        "longest_streak": longest,
    }


def gear_mileage(session: Session) -> list[dict[str, Any]]:
    """Provider-reported gear distance plus what Paceboard can actually see."""
    rows = session.execute(select(Gear)).scalars().all()
    out: list[dict[str, Any]] = []
    for gear in rows:
        observed = session.execute(
            select(func.sum(Activity.distance_m), func.count(Activity.id))
            .where(Activity.gear_id == gear.id)
        ).one()
        out.append({
            "id": gear.id,
            "source": gear.source,
            "provider_id": gear.provider_id,
            "name": gear.name,
            "brand": gear.brand,
            "model": gear.model,
            "gear_type": gear.gear_type,
            "retired": gear.retired,
            "provider_distance_m": gear.provider_distance_m,
            "observed_distance_m": float(observed[0] or 0),
            "observed_activity_count": observed[1] or 0,
        })
    return out


def personal_records(session: Session) -> list[dict[str, Any]]:
    rows = session.execute(
        select(PerformanceMetric)
        .where(PerformanceMetric.metric.like("pr:%"))
        .order_by(PerformanceMetric.day.desc())
    ).scalars().all()
    return [
        {
            "record": row.metric.split(":", 1)[1],
            "source": row.source,
            "day": row.day.isoformat() if (row.context or {}).get("date_known") else None,
            "value": row.value,
            "display": row.text_value,
            "units": row.units,
            "context": row.context,
        }
        for row in rows
    ]


def recompute_derived(session: Session, days: int = 90) -> int:
    """Recalculate and persist the headline derived metrics. Idempotent."""
    end = date.today()
    start = end - timedelta(days=days - 1)
    written = 0

    series = load_series(session, start, end)
    for index, day in enumerate(series["days"]):
        for metric, key, units in (
            ("ctl", "ctl", "au"), ("atl", "atl", "au"), ("tsb", "tsb", "au"),
            ("daily_load", "daily_load", "au"),
        ):
            value = MetricValue(
                series[key][index], units,
                inputs=["activities.avg_hr", "daily_health.resting_hr"],
            )
            if store_metric(session, metric, "day", day, value) is not None:
                written += 1

    for name, metric in monotony_and_strain(session, end).items():
        if store_metric(session, name, "week", end.isoformat(), metric) is not None:
            written += 1

    for bucket in weekly_volume(session, start, end):
        key = f"{bucket['week_start']}:{bucket['sport']}"
        for metric, field_name, units in (
            ("weekly_distance", "distance_m", "m"),
            ("weekly_duration", "duration_s", "s"),
            ("weekly_elevation", "elevation_m", "m"),
        ):
            value = MetricValue(bucket[field_name], units, inputs=["activities"])
            if store_metric(session, metric, "week_sport", key, value) is not None:
                written += 1

    log.info("Recomputed derived metrics", extra={"rows": written, "days": days})
    return written
