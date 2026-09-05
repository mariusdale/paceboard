"""The sync orchestrator: provider calls in, normalized rows out.

A sync run is a sequence of *tasks* (account, activities, daily health,
training, activity enrichment). Each task records its own outcome, so a run can
finish ``partial`` — some categories succeeded, some failed — instead of the
whole thing being lost to one unavailable metric.

Idempotency comes from three places: raw payloads are keyed by
``(provider, endpoint, params)``, normalized rows by their natural keys, and
activity enrichment by a per-record ``detail_status`` watermark. Running the same
backfill twice writes the same rows twice and produces the same database.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any, Iterable, Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..config import Settings, get_settings
from ..db.models import (
    Activity,
    ActivitySourceRecord,
    ProviderCapability,
    ProviderConnection,
    SyncError,
    SyncRun,
    SyncWatermark,
)
from ..db.session import session_scope
from ..logging_conf import get_logger
from ..providers.base import ProviderUnavailable
from ..providers.dto import ProviderResult, ResultStatus
from ..providers.garmin import catalog
from ..providers.registry import ProviderRegistry, get_registry
from ..providers.strava.client import StravaNotConnected
from . import activities as act
from . import normalize_garmin, normalize_strava
from .dedupe import link_source_record
from .raw_store import store_result
from .upsert import upsert

log = get_logger("paceboard.sync")

MODES = ("incremental", "backfill", "today")
ALL_CATEGORIES = ("account", "activities", "daily_health", "training")

#: How many activities get their detail/streams fetched per run. Enrichment is
#: resumable, so a large backfill drains over consecutive runs instead of
#: hammering the provider once.
DETAIL_BATCH = 25
STREAM_BATCH = 10


@dataclass
class SyncRequest:
    providers: tuple[str, ...] = ("garmin", "strava")
    mode: str = "incremental"
    categories: tuple[str, ...] = ALL_CATEGORIES
    start: Optional[date] = None
    end: Optional[date] = None
    trigger: str = "manual"
    enrich: bool = True


@dataclass
class TaskReport:
    name: str
    provider: str
    status: str = "ok"
    records: int = 0
    calls: int = 0
    notes: list[str] = field(default_factory=list)


class SyncOrchestrator:
    """Runs one sync request end to end and records its progress in the DB."""

    def __init__(
        self,
        registry: Optional[ProviderRegistry] = None,
        settings: Optional[Settings] = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.registry = registry or get_registry()

    # -- entry point -----------------------------------------------------

    async def run(self, request: SyncRequest) -> int:
        start, end = self._window(request)
        run_id = self._open_run(request, start, end)
        reports: list[TaskReport] = []
        try:
            for provider_name in request.providers:
                reports.extend(
                    await self._run_provider(run_id, provider_name, request, start, end)
                )
        finally:
            self._close_run(run_id, reports)
        return run_id

    def _window(self, request: SyncRequest) -> tuple[date, date]:
        end = request.end or date.today()
        if request.start:
            return request.start, end
        if request.mode == "backfill":
            return end - timedelta(days=self.settings.backfill_days), end
        if request.mode == "today":
            return end, end
        return end - timedelta(days=self.settings.reconcile_days), end

    def _open_run(self, request: SyncRequest, start: date, end: date) -> int:
        with session_scope() as session:
            run = SyncRun(
                providers=",".join(request.providers),
                mode=request.mode,
                categories=",".join(request.categories),
                status="running",
                trigger=request.trigger,
                started_at=datetime.utcnow(),
                range_start=start,
                range_end=end,
                current_step="starting",
            )
            session.add(run)
            session.flush()
            return run.id

    def _close_run(self, run_id: int, reports: list[TaskReport]) -> None:
        with session_scope() as session:
            run = session.get(SyncRun, run_id)
            if run is None:
                return
            run.finished_at = datetime.utcnow()
            run.records_written = sum(r.records for r in reports)
            run.tasks_total = len(reports)
            run.tasks_done = len(reports)
            failed = [r for r in reports if r.status == "error"]
            attempted = [r for r in reports if r.status != "skipped"]
            run.errors_count = session.execute(
                select(func.count(SyncError.id)).where(SyncError.sync_run_id == run_id)
            ).scalar_one()
            if run.cancel_requested:
                run.status = "cancelled"
            elif not attempted:
                run.status = "error" if failed else "success"
            elif failed and len(failed) == len(attempted):
                run.status = "error"
            elif failed or run.errors_count:
                run.status = "partial"
            else:
                run.status = "success"
            run.current_step = None
            run.summary = {
                "tasks": [
                    {
                        "name": r.name, "provider": r.provider, "status": r.status,
                        "records": r.records, "calls": r.calls, "notes": r.notes[:8],
                    }
                    for r in reports
                ]
            }

    def _step(self, run_id: int, label: str) -> None:
        with session_scope() as session:
            run = session.get(SyncRun, run_id)
            if run is not None:
                run.current_step = label

    def _cancelled(self, run_id: int) -> bool:
        with session_scope() as session:
            run = session.get(SyncRun, run_id)
            return bool(run and run.cancel_requested)

    # -- per provider ----------------------------------------------------

    async def _run_provider(
        self, run_id: int, provider_name: str, request: SyncRequest,
        start: date, end: date,
    ) -> list[TaskReport]:
        provider = self.registry.get(provider_name)

        # A provider the user has not set up is not a failure. Reporting it as
        # one would make every Garmin-only sync finish "partial" with an error
        # row, drowning the real problems the user needs to see.
        if not getattr(provider, "configured", True):
            self._record_connection(
                provider_name, False, "Not configured", status="not_configured"
            )
            return [
                TaskReport(
                    name="connect", provider=provider_name, status="skipped",
                    notes=[f"{provider_name} is not configured; skipped"],
                )
            ]

        try:
            await provider.connect()
        except (ProviderUnavailable, StravaNotConnected) as exc:
            configured_but_unauthorized = getattr(provider, "configured", True) and not getattr(
                provider, "connected", True
            )
            self._record_connection(
                provider_name, False, str(exc),
                status="not_connected" if configured_but_unauthorized else "disconnected",
            )
            if configured_but_unauthorized:
                # Credentials exist but the user has not authorized yet; that is
                # a state to surface in the UI, not a sync failure.
                return [
                    TaskReport(
                        name="connect", provider=provider_name, status="skipped",
                        notes=[str(exc)],
                    )
                ]
            self._record_error(run_id, provider_name, None, "unavailable", str(exc))
            return [
                TaskReport(
                    name="connect", provider=provider_name, status="error",
                    notes=[str(exc)],
                )
            ]

        self._record_connection(provider_name, True, "Connected")
        reports: list[TaskReport] = []

        try:
            capabilities = await provider.discover_capabilities()
            self._store_capabilities(provider_name, capabilities)
            reports.append(
                TaskReport(name="capabilities", provider=provider_name,
                           records=len(capabilities), calls=1)
            )

            if "account" in request.categories:
                self._step(run_id, f"{provider_name}: account")
                reports.append(
                    await self._ingest_results(
                        run_id, provider_name, "account",
                        await provider.fetch_account(),
                    )
                )

            if "activities" in request.categories and not self._cancelled(run_id):
                self._step(run_id, f"{provider_name}: activities")
                reports.append(
                    await self._sync_activities(run_id, provider_name, provider, start, end)
                )

            day_categories = [c for c in ("daily_health", "training") if c in request.categories]
            if day_categories and not self._cancelled(run_id):
                self._step(run_id, f"{provider_name}: daily metrics")
                reports.append(
                    await self._sync_days(
                        run_id, provider_name, provider, start, end, day_categories
                    )
                )
                reports.append(
                    await self._ingest_results(
                        run_id, provider_name, "range",
                        await provider.fetch_range(start, end, day_categories),
                    )
                )

            if request.enrich and "activities" in request.categories and not self._cancelled(run_id):
                self._step(run_id, f"{provider_name}: activity details")
                reports.append(await self._enrich_activities(run_id, provider_name, provider, retry_unavailable=request.mode == "backfill"))
        finally:
            self._set_watermark(provider_name, "sync", end)

        return [r for r in reports if r is not None]

    # -- tasks -----------------------------------------------------------

    async def _ingest_results(
        self, run_id: int, provider_name: str, task_name: str,
        results: Iterable[ProviderResult],
    ) -> TaskReport:
        results = list(results)
        report = TaskReport(name=task_name, provider=provider_name, calls=len(results))
        normalizer = (
            normalize_garmin if provider_name == "garmin" else normalize_strava
        )
        with session_scope() as session:
            for result in results:
                raw = store_result(session, result, sync_run_id=run_id)
                if result.status is ResultStatus.OK:
                    handler_name = self._handler_for(provider_name, result.endpoint)
                    handler = normalizer.get_handler(handler_name)
                    if handler is not None:
                        try:
                            report.records += handler(session, result, raw.id)
                        except Exception as exc:  # one bad payload must not kill the run
                            log.warning(
                                "Normalizer failed",
                                extra={"endpoint": result.endpoint,
                                       "handler": handler_name,
                                       "error": type(exc).__name__},
                            )
                            self._record_error(
                                run_id, provider_name, result.endpoint, "normalize",
                                f"{type(exc).__name__} while normalizing", session=session,
                            )
                            report.status = "partial"
                elif result.status.is_permanent:
                    report.notes.append(f"{result.endpoint}: {result.status.value}")
                else:
                    report.status = "partial"
                    self._record_error(
                        run_id, provider_name, result.endpoint, result.status.value,
                        result.message or result.status.value, session=session,
                    )
                self._touch_capability(session, provider_name, result)
        return report

    @staticmethod
    def _handler_for(provider_name: str, endpoint: str) -> Optional[str]:
        if provider_name == "garmin":
            spec = catalog.TOOLS_BY_NAME.get(endpoint)
            return spec.handler if spec else None
        return normalize_strava.handler_for_endpoint(endpoint)

    async def _sync_days(
        self, run_id: int, provider_name: str, provider, start: date, end: date,
        categories: list[str],
    ) -> TaskReport:
        report = TaskReport(name="daily", provider=provider_name)
        day = start
        while day <= end:
            if self._cancelled(run_id):
                report.notes.append("cancelled")
                break
            results = await provider.fetch_daily(day, categories)
            if results:
                partial = await self._ingest_results(
                    run_id, provider_name, f"daily:{day}", results
                )
                report.records += partial.records
                report.calls += partial.calls
                if partial.status != "ok":
                    report.status = "partial"
            day += timedelta(days=1)
        return report

    async def _sync_activities(
        self, run_id: int, provider_name: str, provider, start: date, end: date
    ) -> TaskReport:
        report = TaskReport(name="activities", provider=provider_name)
        summaries, results = await provider.fetch_activities(start, end)
        report.calls = len(results)
        with session_scope() as session:
            for result in results:
                store_result(session, result, sync_run_id=run_id)
                self._touch_capability(session, provider_name, result)
                if not result.ok and not result.status.is_permanent:
                    report.status = "partial"
                    self._record_error(
                        run_id, provider_name, result.endpoint, result.status.value,
                        result.message or "activity list failed", session=session,
                    )
            for dto in summaries:
                row = act.upsert_source_record(session, dto)
                link_source_record(session, row, self.settings)
                report.records += 1
        return report

    async def _enrich_activities(
        self, run_id: int, provider_name: str, provider, *, retry_unavailable: bool = False
    ) -> TaskReport:
        """Fetch detail/laps/zones then streams for records that still need them."""
        report = TaskReport(name="activity_detail", provider=provider_name)

        with session_scope() as session:
            pending = list(
                session.execute(
                    select(ActivitySourceRecord.provider_id)
                    .where(
                        ActivitySourceRecord.source == provider_name,
                        ActivitySourceRecord.detail_status.in_(("pending", "retry", "unavailable") if retry_unavailable else ("pending", "retry")),
                    )
                    .order_by(ActivitySourceRecord.start_time_utc.desc())
                    .limit(DETAIL_BATCH)
                ).scalars()
            )

        for provider_id in pending:
            if self._cancelled(run_id):
                report.notes.append("cancelled")
                return report
            report.calls += 1
            try:
                await self._enrich_one(run_id, provider_name, provider, provider_id)
                report.records += 1
            except Exception as exc:
                report.status = "partial"
                self._record_error(
                    run_id, provider_name, "activity_detail", "error",
                    f"{type(exc).__name__} enriching activity", 
                    context={"provider_id": provider_id},
                )

        with session_scope() as session:
            stream_pending = list(
                session.execute(
                    select(ActivitySourceRecord.provider_id)
                    .join(Activity, ActivitySourceRecord.activity_id == Activity.id)
                    .where(
                        ActivitySourceRecord.source == provider_name,
                        ActivitySourceRecord.detail_status == "complete",
                        Activity.stream_status.in_(("pending", "retry", "unavailable") if retry_unavailable else ("pending", "retry")),
                    )
                    .order_by(ActivitySourceRecord.start_time_utc.desc())
                    .limit(STREAM_BATCH)
                ).scalars()
            )

        for provider_id in stream_pending:
            if self._cancelled(run_id):
                return report
            report.calls += 1
            try:
                await self._fetch_streams(run_id, provider_name, provider, provider_id)
            except Exception as exc:
                report.status = "partial"
                self._record_error(
                    run_id, provider_name, "activity_streams", "error",
                    f"{type(exc).__name__} fetching streams",
                    context={"provider_id": provider_id},
                )
        return report

    async def _enrich_one(
        self, run_id: int, provider_name: str, provider, provider_id: str
    ) -> None:
        detail, detail_results = await provider.fetch_activity_detail(provider_id)
        laps, lap_results = await provider.fetch_activity_laps(provider_id)
        zones, zone_results = await provider.fetch_activity_zones(provider_id)
        extra_results: list[ProviderResult] = []
        if provider_name == "garmin":
            extra_results = await asyncio.gather(
                provider.call_tool("get_activity_weather", {"activity_id": provider_id}),
                provider.call_tool("get_activity_typed_splits", {"activity_id": provider_id}),
                provider.call_tool("get_activity_gear", {"activity_id": provider_id}),
            )

        with session_scope() as session:
            for result in [*detail_results, *lap_results, *zone_results, *extra_results]:
                store_result(
                    session, result, sync_run_id=run_id,
                    reference_kind="activity", reference_id=provider_id,
                )
                self._touch_capability(session, provider_name, result)

            requested = session.execute(
                select(ActivitySourceRecord).where(
                    ActivitySourceRecord.source == provider_name,
                    ActivitySourceRecord.provider_id == provider_id,
                )
            ).scalar_one_or_none()
            if requested is None:
                return
            row = requested
            if detail is not None:
                row = act.upsert_source_record(session, detail)
            # Details can correct the summary's timestamp; re-match using that evidence.
            link_source_record(session, row, self.settings)
            act.replace_laps(session, row, laps)
            act.replace_zones(session, row, zones)
            for result in extra_results:
                self._apply_activity_extra(session, row, result)

            status = "complete" if detail is not None else "unavailable"
            row.detail_status = status
            # Always settle the record we asked about. If a provider ever answers
            # with a different id, leaving the requested row "pending" would make
            # every later sync fetch it again forever.
            if requested is not row:
                requested.detail_status = status
                act.ensure_canonical(session, requested)
            for record in {row.id: row, requested.id: requested}.values():
                if record.activity_id:
                    activity = session.get(Activity, record.activity_id)
                    if activity is not None:
                        activity.detail_status = record.detail_status
                        act.rebuild_canonical(session, activity)

    @staticmethod
    def _apply_activity_extra(
        session: Session, row: ActivitySourceRecord, result: ProviderResult
    ) -> None:
        if not result.ok or not isinstance(result.data, (dict, list)):
            return
        if result.endpoint == "get_activity_weather" and isinstance(result.data, dict):
            summary = dict(row.summary or {})
            temperature = result.data.get("temperature")
            if temperature is not None and result.data.get("temperature_unit") in (
                "C", "celsius", None
            ):
                summary["avg_temperature_c"] = temperature
            summary["weather"] = result.data
            row.summary = summary
        elif result.endpoint == "get_activity_typed_splits":
            splits = (
                result.data.get("splits") if isinstance(result.data, dict) else result.data
            )
            if isinstance(splits, list):
                act.replace_splits(session, row, "typed", splits)
        elif result.endpoint == "get_activity_gear":
            entries = result.data if isinstance(result.data, list) else [result.data]
            for entry in entries:
                if isinstance(entry, dict) and entry.get("uuid"):
                    summary = dict(row.summary or {})
                    summary["gear_provider_id"] = str(entry["uuid"])
                    row.summary = summary
        session.flush()

    async def _fetch_streams(
        self, run_id: int, provider_name: str, provider, provider_id: str
    ) -> None:
        streams, results = await provider.fetch_activity_streams(provider_id)
        with session_scope() as session:
            for result in results:
                store_result(
                    session, result, sync_run_id=run_id,
                    reference_kind="activity_streams", reference_id=provider_id,
                )
                self._touch_capability(session, provider_name, result)
            row = session.execute(
                select(ActivitySourceRecord).where(
                    ActivitySourceRecord.source == provider_name,
                    ActivitySourceRecord.provider_id == provider_id,
                )
            ).scalar_one_or_none()
            if row is None:
                return
            written = act.replace_streams(session, row, streams)
            if row.activity_id:
                activity = session.get(Activity, row.activity_id)
                if activity is not None:
                    activity.stream_status = "complete" if written else "unavailable"
                    act.rebuild_canonical(session, activity)

    # -- bookkeeping -----------------------------------------------------

    def _record_connection(
        self, provider: str, ok: bool, detail: str, status: Optional[str] = None
    ) -> None:
        with session_scope() as session:
            now = datetime.utcnow()
            values: dict[str, Any] = {
                "status": status or ("connected" if ok else "disconnected"),
                "last_checked_at": now,
                # "not configured" is a state, not an error to display in red.
                "last_error": None if ok or status == "not_configured" else detail[:500],
            }
            if ok:
                values["last_success_at"] = now
            row = upsert(session, ProviderConnection, {"provider": provider}, values)
            if ok:
                row.last_error = None

    def _store_capabilities(self, provider: str, capabilities) -> None:
        with session_scope() as session:
            for capability in capabilities:
                upsert(
                    session, ProviderCapability,
                    {"provider": provider, "name": capability.name},
                    {
                        "category": capability.category,
                        "scope": capability.scope,
                        "cadence": capability.cadence,
                        "enabled": capability.enabled,
                        "status": capability.status,
                        "handler": capability.handler,
                        "description": capability.description[:2000] or None,
                        "expected_arguments": capability.expected_arguments or None,
                        "input_schema": capability.input_schema,
                    },
                )

    @staticmethod
    def _touch_capability(
        session: Session, provider: str, result: ProviderResult
    ) -> None:
        row = session.execute(
            select(ProviderCapability).where(
                ProviderCapability.provider == provider,
                ProviderCapability.name == result.endpoint,
            )
        ).scalar_one_or_none()
        if row is None:
            return
        row.last_called_at = result.retrieved_at or datetime.utcnow()
        row.last_status = result.status.value
        row.last_note = (result.message or "")[:300] or None
        row.call_count = (row.call_count or 0) + 1
        if not result.status.is_success and not result.status.is_permanent:
            row.error_count = (row.error_count or 0) + 1

    def _record_error(
        self, run_id: int, provider: str, capability: Optional[str], kind: str,
        message: str, *, session: Optional[Session] = None,
        context: Optional[dict[str, Any]] = None,
    ) -> None:
        def write(db: Session) -> None:
            db.add(
                SyncError(
                    sync_run_id=run_id, provider=provider, capability=capability,
                    kind=kind, message=message[:1000], occurred_at=datetime.utcnow(),
                    context=context,
                )
            )

        if session is not None:
            write(session)
        else:
            with session_scope() as db:
                write(db)

    def _set_watermark(self, provider: str, category: str, day: date) -> None:
        with session_scope() as session:
            upsert(
                session, SyncWatermark,
                {"provider": provider, "category": category, "key": ""},
                {
                    "cursor_date": day,
                    "cursor_time": datetime.utcnow(),
                    "last_success_at": datetime.utcnow(),
                    "last_status": "ok",
                },
            )


async def run_sync(request: SyncRequest) -> int:
    return await SyncOrchestrator().run(request)


def request_cancel(run_id: int) -> bool:
    with session_scope() as session:
        run = session.get(SyncRun, run_id)
        if run is None or run.status != "running":
            return False
        run.cancel_requested = True
        return True
