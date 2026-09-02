"""In-process APScheduler jobs.

Cadences follow the operating brief: today's health and recent activities every
15 minutes; a rolling reconciliation of the last few days plus long-term trends
and account metadata once a day. Crucially, the fast job runs only the ``fast``
cadence tools — calling all 50-odd Garmin tools every quarter-hour would burn
the account's rate budget for no benefit.
"""

from __future__ import annotations

import asyncio
from datetime import date, timedelta
from typing import Optional

from ..config import Settings, get_settings
from ..db.session import session_scope
from ..logging_conf import get_logger
from ..analytics.service import recompute_derived
from .sync import SyncRequest, run_sync

log = get_logger("paceboard.scheduler")

_scheduler = None
_lock = asyncio.Lock()


async def _guarded(name: str, request: SyncRequest) -> None:
    """Run one scheduled sync, never overlapping with another."""
    if _lock.locked():
        log.info("Skipping scheduled job; a sync is already running", extra={"job": name})
        return
    async with _lock:
        try:
            run_id = await run_sync(request)
            log.info("Scheduled sync finished", extra={"job": name, "run_id": run_id})
        except Exception:
            log.exception("Scheduled sync failed", extra={"job": name})


async def job_fast() -> None:
    """Today's health snapshot plus any new activities."""
    await _guarded(
        "fast",
        SyncRequest(
            mode="today", categories=("activities", "daily_health"),
            trigger="schedule", enrich=True,
        ),
    )


async def job_daily() -> None:
    """Reconcile the last few days, refresh trends and account metadata."""
    settings = get_settings()
    end = date.today()
    await _guarded(
        "daily",
        SyncRequest(
            mode="incremental",
            categories=("account", "activities", "daily_health", "training"),
            start=end - timedelta(days=settings.reconcile_days),
            end=end,
            trigger="schedule",
            enrich=True,
        ),
    )
    await job_derived()


async def job_derived() -> None:
    try:
        with session_scope() as session:
            recompute_derived(session)
    except Exception:
        log.exception("Derived metric recomputation failed")


def start(settings: Optional[Settings] = None):
    """Start the background scheduler; returns it, or ``None`` when disabled."""
    global _scheduler
    settings = settings or get_settings()
    if not settings.scheduler_enabled:
        log.info("Scheduler disabled (PACEBOARD_SCHEDULER_ENABLED=false)")
        return None
    if _scheduler is not None:
        return _scheduler

    from apscheduler.schedulers.asyncio import AsyncIOScheduler
    from apscheduler.triggers.cron import CronTrigger
    from apscheduler.triggers.interval import IntervalTrigger

    scheduler = AsyncIOScheduler(timezone=settings.timezone)
    scheduler.add_job(
        job_fast,
        IntervalTrigger(minutes=max(5, settings.fast_interval_minutes)),
        id="paceboard-fast", name="Recent activities and today's health",
        max_instances=1, coalesce=True, misfire_grace_time=300,
    )
    scheduler.add_job(
        job_daily,
        CronTrigger(hour=settings.daily_hour_local, minute=15),
        id="paceboard-daily", name="Daily reconciliation and trends",
        max_instances=1, coalesce=True, misfire_grace_time=3600,
    )
    scheduler.add_job(
        job_derived,
        IntervalTrigger(hours=6),
        id="paceboard-derived", name="Recompute derived metrics",
        max_instances=1, coalesce=True,
    )
    scheduler.start()
    _scheduler = scheduler
    log.info(
        "Scheduler started",
        extra={"fast_minutes": settings.fast_interval_minutes,
               "daily_hour": settings.daily_hour_local, "tz": settings.timezone},
    )
    return scheduler


def shutdown() -> None:
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None


def jobs() -> list[dict[str, object]]:
    if _scheduler is None:
        return []
    return [
        {
            "id": job.id,
            "name": job.name,
            "next_run_at": job.next_run_time.isoformat() if job.next_run_time else None,
        }
        for job in _scheduler.get_jobs()
    ]
