"""Sync orchestration: idempotency, partial failure, enrichment, watermarks."""

from __future__ import annotations

from datetime import date, timedelta

import pytest
from sqlalchemy import func, select

from paceboard_api.db.models import (
    Activity,
    ActivityLap,
    ActivitySourceRecord,
    ActivityStream,
    ActivityZone,
    DailyHealth,
    ProviderCapability,
    ProviderConnection,
    RawPayload,
    SleepRecord,
    SyncError,
    SyncRun,
    SyncWatermark,
)
from paceboard_api.ingest.activities import decode_stream
from paceboard_api.ingest.sync import SyncOrchestrator, SyncRequest
from paceboard_api.providers.garmin.provider import GarminMcpProvider
from paceboard_api.providers.registry import ProviderRegistry

from . import fixtures
from .conftest import FakeMcpClient

WINDOW_START = date(2026, 8, 19)
WINDOW_END = date(2026, 8, 20)


class StubRegistry(ProviderRegistry):
    """Only Garmin is wired; Strava stays unconfigured, as in a fresh install."""

    def __init__(self, settings, client):
        super().__init__(settings)
        self._garmin = GarminMcpProvider(client)


@pytest.fixture()
def orchestrator(db, settings, fake_client):
    return SyncOrchestrator(StubRegistry(settings, fake_client), settings)


def request_for(**overrides) -> SyncRequest:
    values = dict(providers=("garmin",), mode="incremental",
                  start=WINDOW_START, end=WINDOW_END, trigger="test")
    values.update(overrides)
    return SyncRequest(**values)


def counts(session) -> dict[str, int]:
    return {
        model.__tablename__: session.execute(
            select(func.count()).select_from(model)
        ).scalar_one()
        for model in (Activity, ActivitySourceRecord, ActivityLap, ActivityZone,
                      ActivityStream, DailyHealth, SleepRecord, RawPayload)
    }


class TestBasicRun:
    async def test_a_run_writes_normalized_rows_and_reports_success(
        self, orchestrator, db
    ):
        run_id = await orchestrator.run(request_for())
        with db.session_scope() as session:
            run = session.get(SyncRun, run_id)
            assert run.status in {"success", "partial"}
            assert run.records_written > 0
            assert run.finished_at is not None
            assert counts(session)["daily_health"] == 2
            assert counts(session)["activities"] == 2

    async def test_capabilities_are_discovered_and_stored(self, orchestrator, db):
        await orchestrator.run(request_for(categories=("account",)))
        with db.session_scope() as session:
            rows = session.execute(select(ProviderCapability)).scalars().all()
            assert rows
            assert {r.status for r in rows} <= {"available", "unavailable", "unmapped"}
            assert any(r.name == "get_stats" for r in rows)

    async def test_connection_state_is_recorded(self, orchestrator, db):
        await orchestrator.run(request_for(categories=("account",)))
        with db.session_scope() as session:
            row = session.execute(select(ProviderConnection)).scalar_one()
            assert row.provider == "garmin"
            assert row.status == "connected"
            assert row.last_success_at is not None

    async def test_a_watermark_is_advanced(self, orchestrator, db):
        await orchestrator.run(request_for())
        with db.session_scope() as session:
            row = session.execute(select(SyncWatermark)).scalar_one()
            assert row.cursor_date == WINDOW_END


class TestIdempotency:
    async def test_running_the_same_window_twice_changes_no_row_counts(
        self, orchestrator, db
    ):
        await orchestrator.run(request_for())
        with db.session_scope() as session:
            before = counts(session)

        await orchestrator.run(request_for())
        with db.session_scope() as session:
            after = counts(session)

        assert before == after

    async def test_repeat_runs_do_not_duplicate_activities(self, orchestrator, db):
        for _ in range(3):
            await orchestrator.run(request_for())
        with db.session_scope() as session:
            records = session.execute(select(ActivitySourceRecord)).scalars().all()
            assert len(records) == 2
            assert len({r.provider_id for r in records}) == 2

    async def test_raw_payloads_are_replaced_not_appended(self, orchestrator, db):
        await orchestrator.run(request_for())
        with db.session_scope() as session:
            first = session.execute(
                select(func.count()).select_from(RawPayload)
            ).scalar_one()

        await orchestrator.run(request_for())
        with db.session_scope() as session:
            assert session.execute(
                select(func.count()).select_from(RawPayload)
            ).scalar_one() == first

    async def test_a_changed_value_updates_the_existing_row(
        self, orchestrator, db, fake_client
    ):
        await orchestrator.run(request_for())
        fake_client.responses["get_stats"] = {**fixtures.GARMIN_STATS, "total_steps": 12000}
        await orchestrator.run(request_for())
        with db.session_scope() as session:
            rows = session.execute(select(DailyHealth)).scalars().all()
            assert len(rows) == 2
            assert any(r.steps == 12000 for r in rows)


class TestPartialFailure:
    async def test_one_failing_tool_does_not_abort_the_run(self, orchestrator, db):
        run_id = await orchestrator.run(request_for())
        with db.session_scope() as session:
            run = session.get(SyncRun, run_id)
            errors = session.execute(
                select(SyncError).where(SyncError.sync_run_id == run_id)
            ).scalars().all()
            # get_endurance_score returns a tool error in the fixture set.
            assert any(e.capability == "get_endurance_score" for e in errors)
            assert run.status == "partial"
            assert run.records_written > 0, "the other tools still wrote their rows"

    async def test_no_data_and_unsupported_are_not_logged_as_errors(
        self, orchestrator, db
    ):
        run_id = await orchestrator.run(request_for())
        with db.session_scope() as session:
            errors = session.execute(
                select(SyncError).where(SyncError.sync_run_id == run_id)
            ).scalars().all()
            capabilities = {e.capability for e in errors}
            assert "get_gear" not in capabilities, "'No gear found.' is not an error"
            assert "get_running_tolerance" not in capabilities

    async def test_absent_results_are_still_stored_as_raw_payloads(
        self, orchestrator, db
    ):
        await orchestrator.run(request_for())
        with db.session_scope() as session:
            statuses = {
                row.endpoint: row.status
                for row in session.execute(select(RawPayload)).scalars()
            }
            assert statuses["get_gear"] == "no_data"
            assert statuses["get_running_tolerance"] == "unsupported"
            assert statuses["get_endurance_score"] == "error"

    async def test_a_totally_unreachable_provider_reports_an_error_run(
        self, db, settings
    ):
        from paceboard_api.providers.base import ProviderUnavailable

        class DeadProvider(GarminMcpProvider):
            async def connect(self):
                raise ProviderUnavailable("garmin", "Cannot reach Garmin MCP")

        registry = ProviderRegistry(settings)
        registry._garmin = DeadProvider(FakeMcpClient({}))
        run_id = await SyncOrchestrator(registry, settings).run(request_for())

        with db.session_scope() as session:
            run = session.get(SyncRun, run_id)
            assert run.status == "error"
            connection = session.execute(select(ProviderConnection)).scalar_one()
            assert connection.status == "disconnected"
            assert "Cannot reach" in connection.last_error

    async def test_a_normalizer_crash_is_contained(self, orchestrator, db, monkeypatch):
        from paceboard_api.ingest import normalize_garmin

        def explode(*_args, **_kwargs):
            raise ValueError("unexpected payload shape")

        monkeypatch.setitem(normalize_garmin._HANDLERS, "daily_stats", explode)
        run_id = await orchestrator.run(request_for())
        with db.session_scope() as session:
            run = session.get(SyncRun, run_id)
            assert run.status == "partial"
            assert counts(session)["sleep_records"] > 0, "other handlers still ran"


class TestEnrichment:
    async def test_details_laps_zones_and_streams_are_fetched(self, orchestrator, db):
        await orchestrator.run(request_for())
        with db.session_scope() as session:
            totals = counts(session)
            # Two activities, each with two laps and five heart-rate zones.
            assert totals["activity_laps"] == 4
            assert totals["activity_zones"] == 10
            assert totals["activity_streams"] > 0

    async def test_streams_decode_back_to_aligned_channels(self, orchestrator, db):
        await orchestrator.run(request_for())
        with db.session_scope() as session:
            rows = {
                row.channel: decode_stream(row.data)
                for row in session.execute(select(ActivityStream)).scalars()
            }
            assert {"time", "heartrate", "distance", "altitude", "lat", "lng"} <= set(rows)
            assert rows["heartrate"] == [140, 141, 142, 143]
            assert len({len(v) for v in rows.values()}) == 1, "channels must align"

    async def test_semicircles_are_converted_to_degrees(self, orchestrator, db):
        await orchestrator.run(request_for())
        with db.session_scope() as session:
            lat = decode_stream(
                session.execute(
                    select(ActivityStream).where(ActivityStream.channel == "lat")
                ).scalars().first().data
            )
            assert 59.9 < lat[0] < 60.1

    async def test_enrichment_is_not_repeated_once_complete(self, orchestrator, db, fake_client):
        await orchestrator.run(request_for())
        first = sum(1 for name, _ in fake_client.calls if name == "get_activity")
        fake_client.calls.clear()
        await orchestrator.run(request_for())
        second = sum(1 for name, _ in fake_client.calls if name == "get_activity")
        assert first == 2
        assert second == 0, "a completed activity must not be re-fetched"

    async def test_the_canonical_activity_absorbs_the_detail_fields(self, orchestrator, db):
        await orchestrator.run(request_for())
        with db.session_scope() as session:
            activity = session.execute(
                select(Activity)
                .join(ActivitySourceRecord, ActivitySourceRecord.activity_id == Activity.id)
                .where(ActivitySourceRecord.provider_id == "24188138095")
            ).scalar_one()
            assert activity.sport == "run"
            assert activity.training_load == pytest.approx(118.0)
            assert activity.aerobic_training_effect == pytest.approx(3.4)
            assert activity.detail_status == "complete"
            assert activity.has_streams is True
            assert activity.has_gps is True


class TestScheduling:
    async def test_the_fast_cadence_calls_only_fast_tools(self, db, settings, fake_client):
        orchestrator = SyncOrchestrator(StubRegistry(settings, fake_client), settings)
        await orchestrator.run(
            SyncRequest(providers=("garmin",), mode="today",
                        categories=("activities", "daily_health"),
                        start=WINDOW_END, end=WINDOW_END, trigger="schedule")
        )
        called = {name for name, _ in fake_client.calls}
        assert "get_stats" in called
        assert "get_activities_by_date" in called
        assert "get_user_profile" not in called, "account tools are daily, not every 15 min"
        assert "get_progress_summary_between_dates" not in called

    async def test_a_range_cap_splits_the_window(self, db, settings, fake_client):
        orchestrator = SyncOrchestrator(StubRegistry(settings, fake_client), settings)
        await orchestrator.run(
            SyncRequest(providers=("garmin",), mode="backfill",
                        start=date(2026, 6, 1), end=date(2026, 8, 31),
                        categories=("training", "daily_health"), trigger="test",
                        enrich=False)
        )
        hrv_calls = [args for name, args in fake_client.calls if name == "get_hrv_trend"]
        assert len(hrv_calls) == 4, "a 92-day window must be split into 30-day chunks"
        for args in hrv_calls:
            start = date.fromisoformat(args["start_date"])
            end = date.fromisoformat(args["end_date"])
            assert (end - start).days < 30


class TestCancellation:
    async def test_a_cancelled_run_stops_and_is_marked_cancelled(
        self, orchestrator, db
    ):
        from paceboard_api.ingest.sync import request_cancel

        original = orchestrator._step

        def cancel_after_first_step(run_id, label):
            original(run_id, label)
            request_cancel(run_id)

        orchestrator._step = cancel_after_first_step
        run_id = await orchestrator.run(
            request_for(start=date(2026, 8, 1), end=WINDOW_END)
        )
        with db.session_scope() as session:
            assert session.get(SyncRun, run_id).status == "cancelled"


class TestRawPayloadRetention:
    """Bulk sample responses keep full provenance but not a duplicate body."""

    async def test_fit_stream_pages_keep_provenance_without_the_body(
        self, orchestrator, db
    ):
        from paceboard_api.ingest.raw_store import BODY_NOT_RETAINED

        await orchestrator.run(request_for())
        with db.session_scope() as session:
            row = session.execute(
                select(RawPayload).where(
                    RawPayload.endpoint == "get_activity_fit_messages"
                )
            ).scalars().first()
            assert row is not None, "the call must still be recorded"
            assert row.endpoint in BODY_NOT_RETAINED
            assert row.content_type == "omitted"
            assert row.content_json is None
            assert "activity_streams" in row.content_text
            assert row.byte_size > 0, "the true payload size is still reported"
            assert row.params["activity_id"]
            assert row.status == "ok"

    async def test_the_samples_themselves_are_still_stored(self, orchestrator, db):
        await orchestrator.run(request_for())
        with db.session_scope() as session:
            rows = session.execute(select(ActivityStream)).scalars().all()
            assert rows, "omitting the raw body must not lose the samples"
            assert any(r.channel == "heartrate" for r in rows)

    async def test_other_endpoints_still_store_their_body_verbatim(
        self, orchestrator, db
    ):
        await orchestrator.run(request_for())
        with db.session_scope() as session:
            row = session.execute(
                select(RawPayload).where(RawPayload.endpoint == "get_stats")
            ).scalars().first()
            assert row.content_type == "json"
            assert row.content_json["total_steps"] == 9124

    async def test_a_failed_stream_call_keeps_its_error_text(self, orchestrator, db, fake_client):
        fake_client.responses["get_activity_fit_messages"] = (
            "Error retrieving FIT data: unavailable"
        )
        await orchestrator.run(request_for())
        with db.session_scope() as session:
            row = session.execute(
                select(RawPayload).where(
                    RawPayload.endpoint == "get_activity_fit_messages"
                )
            ).scalars().first()
            assert row.status == "error"
            assert "Error retrieving FIT data" in row.content_text


class TestUnconfiguredProvider:
    """An unset-up provider is a state to report, never a sync failure."""

    async def test_strava_without_credentials_is_skipped_not_failed(
        self, db, settings, fake_client
    ):
        registry = StubRegistry(settings, fake_client)
        run_id = await SyncOrchestrator(registry, settings).run(
            request_for(providers=("garmin", "strava"))
        )
        with db.session_scope() as session:
            run = session.get(SyncRun, run_id)
            tasks = {t["provider"]: t for t in run.summary["tasks"] if t["name"] == "connect"}
            assert tasks["strava"]["status"] == "skipped"
            assert "not configured" in tasks["strava"]["notes"][0]

            errors = session.execute(
                select(SyncError).where(SyncError.sync_run_id == run_id)
            ).scalars().all()
            assert not any(e.provider == "strava" for e in errors)

            connection = session.execute(
                select(ProviderConnection).where(ProviderConnection.provider == "strava")
            ).scalar_one()
            assert connection.status == "not_configured"
            assert connection.last_error is None

    async def test_a_garmin_only_run_can_still_report_success(
        self, db, settings, garmin_responses
    ):
        # A clean Garmin server plus an unconfigured Strava must not be "partial".
        clean = {k: v for k, v in garmin_responses.items() if k != "get_endurance_score"}
        registry = StubRegistry(settings, FakeMcpClient(clean))
        run_id = await SyncOrchestrator(registry, settings).run(
            request_for(providers=("garmin", "strava"))
        )
        with db.session_scope() as session:
            assert session.get(SyncRun, run_id).status == "success"
