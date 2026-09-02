"""The Overview page's aggregate payload, assembled in one round trip."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

from fastapi import APIRouter
from sqlalchemy import select

from ...analytics import service as analytics
from ...db.models import Activity, DailyHealth, SleepRecord, SyncRun
from ..deps import SessionDep, SettingsDep
from ..schemas import ActivityResponse

router = APIRouter(tags=["overview"])


@router.get("/overview", response_model=dict, summary="Dashboard overview")
def overview(session: SessionDep, settings: SettingsDep) -> dict[str, Any]:
    today = date.today()
    window_start = today - timedelta(days=27)

    latest_health = session.execute(
        select(DailyHealth).where(DailyHealth.day <= today)
        .order_by(DailyHealth.day.desc()).limit(1)
    ).scalar_one_or_none()
    latest_sleep = session.execute(
        select(SleepRecord).order_by(SleepRecord.day.desc()).limit(1)
    ).scalar_one_or_none()

    recent = session.execute(
        select(Activity).order_by(Activity.start_time_utc.desc()).limit(8)
    ).scalars().all()

    load = analytics.load_series(session, window_start, today)
    baselines = _baselines(session, today)

    last_run = session.execute(
        select(SyncRun).order_by(SyncRun.started_at.desc()).limit(1)
    ).scalar_one_or_none()

    return {
        "generated_at": datetime.utcnow().isoformat(),
        "timezone": settings.timezone,
        "unit_system": settings.unit_system,
        "today": {
            "day": latest_health.day.isoformat() if latest_health else None,
            "is_today": bool(latest_health and latest_health.day == today),
            "steps": latest_health.steps if latest_health else None,
            "step_goal": latest_health.step_goal if latest_health else None,
            "resting_hr": latest_health.resting_hr if latest_health else None,
            "avg_stress": latest_health.avg_stress if latest_health else None,
            "body_battery_high": latest_health.body_battery_high if latest_health else None,
            "body_battery_low": latest_health.body_battery_low if latest_health else None,
            "training_readiness": latest_health.training_readiness if latest_health else None,
            "readiness_level": latest_health.readiness_level if latest_health else None,
            "intensity_minutes": (
                (latest_health.moderate_intensity_minutes or 0)
                + 2 * (latest_health.vigorous_intensity_minutes or 0)
                if latest_health else None
            ),
        },
        "last_night": {
            "day": latest_sleep.day.isoformat() if latest_sleep else None,
            "total_sleep_s": latest_sleep.total_sleep_s if latest_sleep else None,
            "sleep_score": latest_sleep.sleep_score if latest_sleep else None,
            "deep_s": latest_sleep.deep_s if latest_sleep else None,
            "light_s": latest_sleep.light_s if latest_sleep else None,
            "rem_s": latest_sleep.rem_s if latest_sleep else None,
            "awake_s": latest_sleep.awake_s if latest_sleep else None,
            "avg_overnight_hrv": latest_sleep.avg_overnight_hrv if latest_sleep else None,
        },
        "baselines": baselines,
        "form": {
            "days": load["days"][-28:],
            "ctl": load["ctl"][-28:],
            "atl": load["atl"][-28:],
            "tsb": load["tsb"][-28:],
            "daily_load": load["daily_load"][-28:],
            "latest_ctl": load["ctl"][-1] if load["ctl"] else None,
            "latest_atl": load["atl"][-1] if load["atl"] else None,
            "latest_tsb": load["tsb"][-1] if load["tsb"] else None,
        },
        "weekly_volume": analytics.weekly_volume(
            session, today - timedelta(days=55), today
        ),
        "rolling": [analytics.rolling_totals(session, d) for d in (7, 28)],
        "consistency": analytics.consistency(session, window_days=90),
        "recent_activities": [
            ActivityResponse.model_validate(row).model_dump() for row in recent
        ],
        "recovery": analytics.recovery_summary(session),
        "sync": {
            "id": last_run.id if last_run else None,
            "status": last_run.status if last_run else None,
            "started_at": last_run.started_at.isoformat() if last_run else None,
            "finished_at": (
                last_run.finished_at.isoformat()
                if last_run and last_run.finished_at else None
            ),
            "current_step": last_run.current_step if last_run else None,
            "records_written": last_run.records_written if last_run else 0,
            "errors_count": last_run.errors_count if last_run else 0,
        },
    }


def _baselines(session, today: date) -> dict[str, Any]:
    """Today's headline numbers against their own trailing averages."""
    window_start = today - timedelta(days=29)
    rows = session.execute(
        select(DailyHealth).where(DailyHealth.day >= window_start)
        .order_by(DailyHealth.day)
    ).scalars().all()
    sleep_rows = session.execute(
        select(SleepRecord).where(SleepRecord.day >= window_start)
        .order_by(SleepRecord.day)
    ).scalars().all()

    def mean(values: list[Any]) -> Any:
        clean = [v for v in values if v is not None]
        return round(sum(clean) / len(clean), 1) if clean else None

    return {
        "window_days": 30,
        "resting_hr": mean([r.resting_hr for r in rows]),
        "avg_stress": mean([r.avg_stress for r in rows]),
        "steps": mean([r.steps for r in rows]),
        "body_battery_high": mean([r.body_battery_high for r in rows]),
        "sleep_seconds": mean([r.total_sleep_s for r in sleep_rows]),
        "sleep_score": mean([r.sleep_score for r in sleep_rows]),
        "training_readiness": mean([r.training_readiness for r in rows]),
    }
