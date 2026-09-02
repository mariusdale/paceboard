"""A read-only MCP server over Paceboard's normalized database.

This is an *interface on top of* Paceboard, not part of its ETL. It answers
questions from data already ingested and never contacts Garmin or Strava — if a
number is missing here, the fix is to run a sync, not to call this server harder.

Every tool is read-only and returns JSON. Arguments are validated before they
reach the database, and no tool exposes raw provider credentials, device serial
numbers, or GPS coordinates.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from typing import Any, Optional

from mcp.server.fastmcp import FastMCP
from sqlalchemy import func, select

from ..analytics import service as analytics
from ..db.models import (
    Activity,
    DailyHealth,
    PerformanceMetric,
    ProviderCapability,
    SleepRecord,
    SyncRun,
    SyncWatermark,
)
from ..db.session import session_scope

app = FastMCP("Paceboard")

MAX_LIMIT = 200
MAX_RANGE_DAYS = 1100


def _dumps(payload: Any) -> str:
    return json.dumps(payload, indent=2, default=str)


def _window(start: Optional[str], end: Optional[str], default_days: int) -> tuple[date, date]:
    """Parse and bound a date window; raises ValueError on malformed input."""
    resolved_end = date.fromisoformat(end) if end else date.today()
    resolved_start = (
        date.fromisoformat(start) if start else resolved_end - timedelta(days=default_days - 1)
    )
    if resolved_start > resolved_end:
        raise ValueError("start_date must be on or before end_date")
    if (resolved_end - resolved_start).days + 1 > MAX_RANGE_DAYS:
        raise ValueError(f"Date range must not exceed {MAX_RANGE_DAYS} days")
    return resolved_start, resolved_end


@app.tool()
def query_activities(
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    sport: Optional[str] = None,
    limit: int = 25,
) -> str:
    """List stored activities, newest first.

    Reads Paceboard's canonical activity table, which merges Garmin and Strava
    records for the same session.

    Args:
        start_date: Inclusive ISO date. Defaults to 90 days before end_date.
        end_date: Inclusive ISO date. Defaults to today.
        sport: Canonical sport to filter by (run, ride, swim, walk, hike, ...).
        limit: Maximum activities to return (1-200).
    """
    start, end = _window(start_date, end_date, 90)
    limit = max(1, min(limit, MAX_LIMIT))
    with session_scope() as session:
        stmt = select(Activity).where(
            Activity.start_time_utc >= datetime.combine(start, datetime.min.time()),
            Activity.start_time_utc <= datetime.combine(end, datetime.max.time()),
        )
        if sport:
            stmt = stmt.where(Activity.sport == sport)
        rows = session.execute(
            stmt.order_by(Activity.start_time_utc.desc()).limit(limit)
        ).scalars().all()
        return _dumps({
            "range": {"start": start.isoformat(), "end": end.isoformat()},
            "count": len(rows),
            "activities": [
                {
                    "id": row.id,
                    "name": row.name,
                    "sport": row.sport,
                    "start_time_utc": row.start_time_utc.isoformat(),
                    "local_date": row.local_date.isoformat() if row.local_date else None,
                    "distance_m": row.distance_m,
                    "moving_duration_s": row.moving_duration_s or row.duration_s,
                    "elevation_gain_m": row.elevation_gain_m,
                    "avg_hr": row.avg_hr,
                    "avg_power_w": row.avg_power_w,
                    "training_load": row.training_load,
                    "sources": [s.source for s in row.sources],
                }
                for row in rows
            ],
        })


@app.tool()
def get_activity_analysis(activity_id: int) -> str:
    """Derived analysis for one stored activity.

    Returns TRIMP, cardiac drift, normalized power, intensity factor, TSS,
    watts/kg, best efforts and the power/pace curves — each either with a value
    or with an explicit reason it could not be computed.

    Args:
        activity_id: Paceboard activity id, from query_activities.
    """
    with session_scope() as session:
        activity = session.get(Activity, activity_id)
        if activity is None:
            return _dumps({"error": f"No activity with id {activity_id}"})
        metrics = analytics.activity_stream_metrics(session, activity)
        metrics["trimp"] = analytics.activity_trimp(session, activity)
        return _dumps({
            "activity": {
                "id": activity.id,
                "name": activity.name,
                "sport": activity.sport,
                "start_time_utc": activity.start_time_utc.isoformat(),
                "distance_m": activity.distance_m,
                "moving_duration_s": activity.moving_duration_s or activity.duration_s,
            },
            "metrics": {name: value.as_dict() for name, value in metrics.items()},
            "field_provenance": activity.field_provenance,
        })


@app.tool()
def get_recovery_summary(end_date: Optional[str] = None) -> str:
    """Current recovery picture: HRV against baseline, sleep debt and consistency.

    Args:
        end_date: Inclusive ISO date to summarize up to. Defaults to today.
    """
    with session_scope() as session:
        parsed = date.fromisoformat(end_date) if end_date else None
        return _dumps(analytics.recovery_summary(session, parsed))


@app.tool()
def get_training_load(start_date: Optional[str] = None, end_date: Optional[str] = None) -> str:
    """Fitness, fatigue and form over a window, plus monotony and strain.

    CTL/ATL/TSB are computed by Paceboard from per-activity Banister TRIMP.
    Garmin's own acute/chronic load is returned alongside, in Garmin's units.

    Args:
        start_date: Inclusive ISO date. Defaults to 90 days before end_date.
        end_date: Inclusive ISO date. Defaults to today.
    """
    start, end = _window(start_date, end_date, 90)
    with session_scope() as session:
        series = analytics.load_series(session, start, end)
        series["monotony_and_strain"] = {
            name: value.as_dict()
            for name, value in analytics.monotony_and_strain(session, end).items()
        }
        series["zones"] = analytics.zone_totals(session, start, end)
        return _dumps(series)


@app.tool()
def compare_periods(
    period_a_start: str,
    period_a_end: str,
    period_b_start: str,
    period_b_end: str,
) -> str:
    """Compare training volume and recovery between two date windows.

    Args:
        period_a_start: Inclusive ISO start of the first window.
        period_a_end: Inclusive ISO end of the first window.
        period_b_start: Inclusive ISO start of the second window.
        period_b_end: Inclusive ISO end of the second window.
    """
    windows = {
        "period_a": _window(period_a_start, period_a_end, 28),
        "period_b": _window(period_b_start, period_b_end, 28),
    }
    with session_scope() as session:
        out: dict[str, Any] = {}
        for name, (start, end) in windows.items():
            totals = session.execute(
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
            sleep = session.execute(
                select(func.avg(SleepRecord.total_sleep_s), func.avg(SleepRecord.sleep_score))
                .where(SleepRecord.day >= start, SleepRecord.day <= end)
            ).one()
            rhr = session.execute(
                select(func.avg(DailyHealth.resting_hr))
                .where(DailyHealth.day >= start, DailyHealth.day <= end)
            ).scalar()
            load = analytics.load_series(session, start, end)
            out[name] = {
                "range": {"start": start.isoformat(), "end": end.isoformat()},
                "activity_count": totals[0] or 0,
                "distance_m": float(totals[1] or 0),
                "duration_s": float(totals[2] or 0),
                "elevation_m": float(totals[3] or 0),
                "total_load": round(sum(load["daily_load"]), 1),
                "avg_sleep_s": float(sleep[0]) if sleep[0] is not None else None,
                "avg_sleep_score": float(sleep[1]) if sleep[1] is not None else None,
                "avg_resting_hr": float(rhr) if rhr is not None else None,
            }
        a, b = out["period_a"], out["period_b"]
        out["delta"] = {
            key: (None if a.get(key) is None or b.get(key) is None else b[key] - a[key])
            for key in ("activity_count", "distance_m", "duration_s", "elevation_m",
                        "total_load", "avg_sleep_s", "avg_sleep_score", "avg_resting_hr")
        }
        return _dumps(out)


@app.tool()
def find_correlations(days: int = 90) -> str:
    """Correlations between recovery markers and training load.

    These are observational associations within one athlete's own history. Each
    row reports the sample size; treat them as descriptive, not causal.

    Args:
        days: Window size in days (14-730).
    """
    days = max(14, min(days, 730))
    with session_scope() as session:
        return _dumps({
            "window_days": days,
            "note": "Association within a single athlete's history. Not causal.",
            "correlations": analytics.correlations(session, window_days=days),
        })


@app.tool()
def get_data_freshness() -> str:
    """What Paceboard holds and how current it is.

    Use this before trusting an answer: if a category was last synced days ago,
    the numbers below it are that old.
    """
    with session_scope() as session:
        counts = {
            "activities": session.execute(select(func.count()).select_from(Activity)).scalar_one(),
            "daily_health": session.execute(select(func.count()).select_from(DailyHealth)).scalar_one(),
            "sleep_records": session.execute(select(func.count()).select_from(SleepRecord)).scalar_one(),
            "performance_metrics": session.execute(select(func.count()).select_from(PerformanceMetric)).scalar_one(),
        }
        last_run = session.execute(
            select(SyncRun).order_by(SyncRun.started_at.desc()).limit(1)
        ).scalar_one_or_none()
        watermarks = session.execute(select(SyncWatermark)).scalars().all()
        capabilities = session.execute(
            select(ProviderCapability.provider, ProviderCapability.status, func.count())
            .group_by(ProviderCapability.provider, ProviderCapability.status)
        ).all()
        latest_activity = session.execute(
            select(func.max(Activity.start_time_utc))
        ).scalar()
        latest_health = session.execute(select(func.max(DailyHealth.day))).scalar()
        return _dumps({
            "counts": counts,
            "latest_activity_utc": latest_activity.isoformat() if latest_activity else None,
            "latest_health_day": latest_health.isoformat() if latest_health else None,
            "last_sync": {
                "id": last_run.id,
                "status": last_run.status,
                "finished_at": last_run.finished_at.isoformat() if last_run.finished_at else None,
                "records_written": last_run.records_written,
                "errors_count": last_run.errors_count,
            } if last_run else None,
            "watermarks": [
                {
                    "provider": w.provider, "category": w.category,
                    "cursor_date": w.cursor_date.isoformat() if w.cursor_date else None,
                    "last_success_at": w.last_success_at.isoformat() if w.last_success_at else None,
                }
                for w in watermarks
            ],
            "capabilities": [
                {"provider": provider, "status": status, "count": count}
                for provider, status, count in capabilities
            ],
        })


def main() -> None:
    """Run the Paceboard MCP server over stdio (for Claude Desktop / Claude Code)."""
    import os

    transport = os.getenv("PACEBOARD_MCP_TRANSPORT", "stdio").strip().lower()
    if transport == "streamable-http":
        app.settings.host = os.getenv("PACEBOARD_MCP_HOST", "127.0.0.1")
        app.settings.port = int(os.getenv("PACEBOARD_MCP_PORT", "8788"))
        app.run(transport="streamable-http")
    else:
        app.run(transport="stdio")


if __name__ == "__main__":
    main()
