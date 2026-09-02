"""REST API: filtering, pagination, typed errors and the safety boundaries."""

from __future__ import annotations

from datetime import date, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from paceboard_api.db.models import (
    Activity,
    ActivityLap,
    ActivitySourceRecord,
    ActivityStream,
    ActivityZone,
    DailyHealth,
    DuplicateCandidate,
    Gear,
    ProviderCapability,
    RawPayload,
    SleepRecord,
    SyncRun,
)
from paceboard_api.ingest.activities import encode_stream
from paceboard_api.main import create_app


@pytest.fixture()
def client(db, settings):
    """A TestClient with the scheduler and provider connections disabled."""
    app = create_app(settings)
    # The lifespan starts the scheduler and opens provider sessions; neither is
    # wanted here, and the routes under test only read the database.
    with TestClient(app, raise_server_exceptions=False) as test_client:
        yield test_client


@pytest.fixture()
def seeded(db):
    with db.session_scope() as session:
        for index in range(12):
            day = date(2026, 8, 31) - timedelta(days=index)
            start = datetime.combine(day, datetime.min.time()) + timedelta(hours=6)
            sport = "run" if index % 2 else "ride"
            activity = Activity(
                canonical_key=f"garmin:{index}", primary_source="garmin",
                name=f"Session {index}", sport=sport, start_time_utc=start,
                local_date=day, duration_s=3600, moving_duration_s=3500,
                distance_m=10000 + index * 100, elevation_gain_m=100,
                avg_hr=150, max_hr=175, has_gps=index == 0, has_streams=index == 0,
                field_provenance={"distance_m": "garmin"},
            )
            session.add(activity)
            session.flush()
            record = ActivitySourceRecord(
                activity_id=activity.id, source="garmin", provider_id=f"g{index}",
                sport=sport, start_time_utc=start, duration_s=3600,
                distance_m=10000 + index * 100, summary={"distance_m": 10000 + index * 100},
            )
            session.add(record)
            session.flush()
            if index == 0:
                session.add(ActivityLap(
                    activity_id=activity.id, source_record_id=record.id, source="garmin",
                    lap_index=1, distance_m=5000, duration_s=1800, avg_hr=148,
                ))
                session.add(ActivityZone(
                    activity_id=activity.id, source_record_id=record.id, source="garmin",
                    zone_kind="hr", zone_number=2, seconds_in_zone=1200,
                ))
                for channel, values in (
                    ("time", [0.0, 1.0, 2.0, 3.0]),
                    ("heartrate", [140.0, 141.0, 142.0, 143.0]),
                    ("lat", [59.9, 59.91, 59.92, 59.93]),
                    ("lng", [10.75, 10.76, 10.77, 10.78]),
                ):
                    session.add(ActivityStream(
                        activity_id=activity.id, source_record_id=record.id,
                        source="garmin", channel=channel, point_count=len(values),
                        data=encode_stream(values),
                    ))
            session.add(DailyHealth(source="garmin", day=day, steps=9000 + index,
                                    resting_hr=48, avg_stress=25))
            session.add(SleepRecord(source="garmin", day=day, total_sleep_s=27000,
                                    sleep_score=82))
        session.add(Gear(source="garmin", provider_id="gear-1", name="Trainers",
                         gear_type="shoes", provider_distance_m=402000))
        session.add(ProviderCapability(
            provider="garmin", name="get_stats", category="daily_health",
            scope="daily", cadence="fast", enabled=True, status="available",
            handler="daily_stats", call_count=3,
        ))
        session.add(ProviderCapability(
            provider="garmin", name="get_running_tolerance", category="training",
            scope="daily", cadence="daily", enabled=True, status="available",
            last_status="unsupported", last_note="Your device does not support this metric.",
        ))
        session.add(RawPayload(
            provider="garmin", endpoint="get_stats", params={"date": "2026-08-31"},
            params_hash="abc123", status="ok", content_type="json",
            content_json={"total_steps": 9000}, byte_size=24,
            retrieved_at=datetime(2026, 8, 31, 6, 0),
        ))
        session.add(RawPayload(
            provider="garmin", endpoint="get_gear", params={}, params_hash="def456",
            status="no_data", content_type="text", content_text="No gear found.",
            byte_size=15, retrieved_at=datetime(2026, 8, 31, 6, 1),
        ))
        session.add(SyncRun(
            providers="garmin", mode="incremental", status="partial", trigger="test",
            started_at=datetime(2026, 8, 31, 6, 0),
            finished_at=datetime(2026, 8, 31, 6, 5),
            records_written=120, errors_count=1,
        ))


class TestStatus:
    def test_status_reports_counts_and_binding(self, client, seeded):
        body = client.get("/api/v1/status").json()
        assert body["app"] == "paceboard"
        assert body["bound_host"] == "127.0.0.1"
        assert body["counts"]["activities"] == 12
        assert body["timezone"] == "Europe/Oslo"

    def test_healthz_is_unauthenticated_and_cheap(self, client):
        assert client.get("/healthz").json()["status"] == "ok"

    def test_openapi_documents_every_route(self, client):
        paths = client.get("/openapi.json").json()["paths"]
        for required in ("/api/v1/status", "/api/v1/activities", "/api/v1/overview",
                         "/api/v1/health/daily", "/api/v1/training/load",
                         "/api/v1/capabilities", "/api/v1/raw-data",
                         "/api/v1/auth/strava/authorize"):
            assert required in paths


class TestActivities:
    def test_pagination_reports_totals_and_more(self, client, seeded):
        body = client.get("/api/v1/activities", params={"limit": 5}).json()
        assert len(body["items"]) == 5
        assert body["page"]["total"] == 12
        assert body["page"]["has_more"] is True

        second = client.get("/api/v1/activities", params={"limit": 5, "offset": 10}).json()
        assert len(second["items"]) == 2
        assert second["page"]["has_more"] is False

    def test_newest_first(self, client, seeded):
        items = client.get("/api/v1/activities").json()["items"]
        stamps = [item["start_time_utc"] for item in items]
        assert stamps == sorted(stamps, reverse=True)

    def test_sport_filter(self, client, seeded):
        items = client.get("/api/v1/activities", params={"sport": "run"}).json()["items"]
        assert items
        assert {i["sport"] for i in items} == {"run"}

    def test_source_filter(self, client, seeded):
        assert client.get("/api/v1/activities", params={"source": "garmin"}).json()["page"]["total"] == 12
        assert client.get("/api/v1/activities", params={"source": "strava"}).json()["page"]["total"] == 0

    def test_an_unknown_source_is_a_typed_bad_request(self, client, seeded):
        response = client.get("/api/v1/activities", params={"source": "fitbit"})
        assert response.status_code == 400
        assert response.json()["error"]["code"] == "bad_request"

    def test_date_range_filter(self, client, seeded):
        body = client.get("/api/v1/activities",
                          params={"start": "2026-08-29", "end": "2026-08-31"}).json()
        assert body["page"]["total"] == 3

    def test_search_filter(self, client, seeded):
        assert client.get("/api/v1/activities",
                          params={"search": "Session 3"}).json()["page"]["total"] == 1

    def test_gps_filter(self, client, seeded):
        assert client.get("/api/v1/activities",
                          params={"has_gps": True}).json()["page"]["total"] == 1

    def test_a_missing_activity_is_a_typed_404(self, client, seeded):
        response = client.get("/api/v1/activities/9999")
        assert response.status_code == 404
        body = response.json()["error"]
        assert body["code"] == "not_found"
        assert "9999" in body["message"]

    def test_detail_includes_source_attribution(self, client, seeded):
        body = client.get("/api/v1/activities/1").json()
        assert body["sources"][0]["source"] == "garmin"
        assert body["field_provenance"]["distance_m"] == "garmin"


class TestStreams:
    def test_streams_are_returned_with_source_and_units(self, client, seeded):
        body = client.get("/api/v1/activities/1/streams").json()
        assert body["available"] is True
        assert body["channels"]["heartrate"]["data"] == [140, 141, 142, 143]
        assert body["channels"]["heartrate"]["source"] == "garmin"

    def test_channel_selection(self, client, seeded):
        body = client.get("/api/v1/activities/1/streams",
                          params={"channels": "lat,lng"}).json()
        assert set(body["channels"]) == {"lat", "lng"}

    def test_downsampling_is_reported_not_silent(self, client, seeded):
        body = client.get("/api/v1/activities/1/streams", params={"max_points": 50}).json()
        assert "downsample_step" in body
        assert body["original_point_count"] == 4

    def test_an_activity_without_streams_states_why(self, client, seeded):
        body = client.get("/api/v1/activities/2/streams").json()
        assert body["available"] is False
        assert body["unavailable_reason"]

    def test_laps_and_zones(self, client, seeded):
        assert len(client.get("/api/v1/activities/1/laps").json()) == 1
        zones = client.get("/api/v1/activities/1/zones").json()
        assert zones["available"] is True
        assert zones["zones"][0]["zone"] == 2

    def test_zones_are_unavailable_with_a_reason_not_empty(self, client, seeded):
        body = client.get("/api/v1/activities/2/zones").json()
        assert body["available"] is False
        assert body["unavailable_reason"]


class TestHealthRoutes:
    def test_daily_series_respects_the_window(self, client, seeded):
        rows = client.get("/api/v1/health/daily",
                          params={"start": "2026-08-25", "end": "2026-08-31"}).json()
        assert len(rows) == 7
        assert all(row["source"] == "garmin" for row in rows)

    def test_days_parameter_is_an_alternative_to_explicit_dates(self, client, seeded):
        rows = client.get("/api/v1/health/daily", params={"days": 3, "end": "2026-08-31"}).json()
        assert len(rows) == 3

    def test_start_after_end_is_rejected(self, client, seeded):
        response = client.get("/api/v1/health/daily",
                              params={"start": "2026-08-31", "end": "2026-08-01"})
        assert response.status_code == 400
        assert response.json()["error"]["code"] == "bad_request"

    def test_an_excessive_window_is_rejected(self, client, seeded):
        response = client.get("/api/v1/health/daily", params={"days": 99999})
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "validation_error"

    def test_recovery_summary_states_reasons(self, client, db):
        body = client.get("/api/v1/health/recovery/summary").json()
        assert body["hrv_latest"]["available"] is False
        assert body["hrv_latest"]["unavailable_reason"]

    def test_sleep_and_hrv_routes(self, client, seeded):
        # Pin the window end: the seeded history stops at 2026-08-31, so a
        # window relative to "today" would make this test drift with the clock.
        window = {"days": 12, "end": "2026-08-31"}
        assert len(client.get("/api/v1/health/sleep", params=window).json()) == 12
        assert client.get("/api/v1/health/hrv", params=window).json() == []


class TestTrainingRoutes:
    def test_load_documents_its_formula_and_keeps_providers_separate(self, client, seeded):
        body = client.get("/api/v1/training/load", params={"days": 30}).json()
        assert "ctl" in body and "garmin_chronic" in body
        assert "TRIMP" in body["formula"]["daily_load"]
        assert "not blended" in body["provider_note"]

    def test_zones_report_a_reason_when_absent(self, client, db):
        body = client.get("/api/v1/training/zones", params={"days": 30}).json()
        assert body["available"] is False
        assert body["unavailable_reason"]

    def test_performance_is_empty_with_a_reason(self, client, seeded):
        body = client.get("/api/v1/training/performance", params={"days": 30}).json()
        assert body["available"] is False
        assert body["unavailable_reason"]

    def test_volume_and_rolling(self, client, seeded):
        assert client.get("/api/v1/training/volume", params={"days": 30}).json()
        assert len(client.get("/api/v1/training/rolling").json()) == 4


class TestOverview:
    def test_overview_assembles_every_panel(self, client, seeded):
        body = client.get("/api/v1/overview").json()
        for key in ("today", "last_night", "baselines", "form", "weekly_volume",
                    "rolling", "consistency", "recent_activities", "recovery", "sync"):
            assert key in body
        assert len(body["recent_activities"]) <= 8

    def test_overview_works_on_an_empty_database(self, client, db):
        body = client.get("/api/v1/overview").json()
        assert body["today"]["day"] is None
        assert body["recent_activities"] == []


class TestCapabilitiesAndRaw:
    def test_capabilities_can_be_filtered(self, client, seeded):
        assert len(client.get("/api/v1/capabilities").json()) == 2
        rows = client.get("/api/v1/capabilities", params={"category": "training"}).json()
        assert rows[0]["name"] == "get_running_tolerance"
        assert rows[0]["last_status"] == "unsupported"

    def test_raw_payload_listing_includes_coverage(self, client, seeded):
        body = client.get("/api/v1/raw-data").json()
        assert body["page"]["total"] == 2
        assert {e["endpoint"] for e in body["endpoints"]} == {"get_stats", "get_gear"}

    def test_raw_payloads_can_be_filtered_by_result(self, client, seeded):
        body = client.get("/api/v1/raw-data", params={"status": "no_data"}).json()
        assert body["page"]["total"] == 1
        assert body["items"][0]["endpoint"] == "get_gear"

    def test_a_text_payload_is_returned_verbatim(self, client, seeded):
        payload_id = client.get("/api/v1/raw-data",
                                params={"status": "no_data"}).json()["items"][0]["id"]
        body = client.get(f"/api/v1/raw-data/{payload_id}").json()
        assert body["content"] == "No gear found."


class TestToolInvocationGuards:
    def test_the_tool_list_contains_no_mutating_tool(self, client):
        from paceboard_api.providers.garmin.catalog import is_mutating

        names = [tool["name"] for tool in client.get("/api/v1/tools").json()]
        assert names
        assert not any(is_mutating(name) for name in names)

    @pytest.mark.parametrize(
        "tool",
        ["set_activity_name", "delete_workout", "add_weigh_in", "upload_workout",
         "create_run_workout", "download_activity_file", "request_reload"],
    )
    def test_a_mutating_tool_is_refused(self, client, tool):
        response = client.post("/api/v1/tools/call", json={"tool": tool, "arguments": {}})
        assert response.status_code == 400
        assert "allowlist" in response.json()["error"]["message"]

    def test_an_unknown_tool_is_refused(self, client):
        response = client.post("/api/v1/tools/call",
                               json={"tool": "get_everything", "arguments": {}})
        assert response.status_code == 400

    def test_an_unexpected_argument_is_refused_before_any_call(self, client):
        response = client.post("/api/v1/tools/call",
                               json={"tool": "get_stats",
                                     "arguments": {"date": "2026-08-31", "sql": "drop"}})
        assert response.status_code == 400
        body = response.json()["error"]
        assert "sql" in body["message"]
        assert body["detail"]["allowed"] == ["date"]

    def test_an_oversized_argument_is_refused(self, client):
        response = client.post("/api/v1/tools/call",
                               json={"tool": "get_stats", "arguments": {"date": "x" * 5000}})
        assert response.status_code == 400


class TestExport:
    def test_datasets_are_listed(self, client):
        names = {row["name"] for row in client.get("/api/v1/export/datasets").json()}
        assert {"activities", "daily_health", "raw_payloads"} <= names

    def test_csv_export_has_a_header_and_rows(self, client, seeded):
        response = client.get("/api/v1/export.csv",
                              params={"dataset": "daily_health", "days": 30})
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/csv")
        lines = response.text.strip().splitlines()
        assert lines[0].startswith("id,source,day")
        assert len(lines) == 13

    def test_json_export_carries_the_window(self, client, seeded):
        body = client.get("/api/v1/export.json",
                          params={"dataset": "activities", "days": 30}).json()
        assert body["dataset"] == "activities"
        assert body["range"]["end"]
        assert len(body["rows"]) == 12

    def test_an_unknown_dataset_lists_the_valid_ones(self, client):
        response = client.get("/api/v1/export.csv", params={"dataset": "secrets"})
        assert response.status_code == 400
        assert "available" in response.json()["error"]["detail"]

    def test_device_serial_numbers_are_never_exported(self, client):
        from paceboard_api.api.routers.export import EXCLUDED_COLUMNS

        assert "serial_number" in EXCLUDED_COLUMNS


class TestDeletion:
    def test_deletion_requires_the_confirmation_to_match(self, client, seeded):
        response = client.delete("/api/v1/data", params={"scope": "raw", "confirm": "yes"})
        assert response.status_code == 400

    def test_deleting_raw_payloads_leaves_normalized_data(self, client, seeded, db):
        body = client.delete("/api/v1/data",
                             params={"scope": "raw", "confirm": "raw"}).json()
        assert body["deleted"]["raw_payloads"] == 2
        assert client.get("/api/v1/activities").json()["page"]["total"] == 12

    def test_an_invalid_scope_is_rejected_by_validation(self, client):
        response = client.delete("/api/v1/data",
                                 params={"scope": "everything", "confirm": "everything"})
        assert response.status_code == 422


class TestStravaRoutes:
    def test_status_reports_not_configured_without_credentials(self, client):
        body = client.get("/api/v1/auth/strava/status").json()
        assert body["configured"] is False
        assert body["connected"] is False
        assert "STRAVA_CLIENT_ID" in body["message"]

    def test_authorize_without_credentials_is_a_typed_503(self, client):
        response = client.get("/api/v1/auth/strava/authorize")
        assert response.status_code == 503
        assert response.json()["error"]["code"] == "provider_unavailable"

    def test_the_callback_rejects_an_unknown_state(self, client):
        response = client.get("/api/v1/auth/strava/callback",
                              params={"code": "abc", "state": "forged"})
        assert response.status_code == 400
        assert "State mismatch" in response.text

    def test_the_callback_reports_a_declined_authorization(self, client):
        response = client.get("/api/v1/auth/strava/callback", params={"error": "access_denied"})
        assert "declined" in response.text.lower()

    def test_webhooks_are_disabled_without_a_verify_token(self, client):
        response = client.get("/api/v1/auth/strava/webhook",
                              params={"hub.mode": "subscribe", "hub.challenge": "x",
                                      "hub.verify_token": "y"})
        assert response.status_code == 503

    def test_connections_never_leak_token_material(self, client):
        text = client.get("/api/v1/connections").text
        assert "access_token" not in text
        assert "client_secret" not in text
        assert "refresh_token" not in text


class TestSettingsRoutes:
    def test_maps_are_off_by_default(self, client):
        body = client.get("/api/v1/settings").json()
        assert body["show_maps"] is False
        assert body["map_tiles_enabled"] is False
        assert "third-party" in body["notes"]["map_tiles"]

    def test_settings_round_trip(self, client):
        body = client.put("/api/v1/settings",
                          json={"unit_system": "imperial", "show_maps": True}).json()
        assert body["unit_system"] == "imperial"
        assert body["show_maps"] is True
        assert client.get("/api/v1/settings").json()["unit_system"] == "imperial"

    def test_an_invalid_unit_system_is_rejected(self, client):
        assert client.put("/api/v1/settings", json={"unit_system": "furlongs"}).status_code == 422

    def test_storage_statistics_are_reported(self, client, seeded):
        storage = client.get("/api/v1/settings").json()["storage"]
        assert storage["rows"]["activities"] == 12
        assert storage["total_rows"] > 0


class TestSecurityHeaders:
    def test_responses_are_not_cacheable(self, client):
        headers = client.get("/api/v1/status").headers
        assert headers["cache-control"] == "no-store"
        assert headers["referrer-policy"] == "no-referrer"
        assert headers["x-content-type-options"] == "nosniff"

    def test_cors_allows_only_the_local_dashboard(self, settings):
        assert settings.cors_origins == [
            "http://127.0.0.1:3000", "http://localhost:3000",
        ]

    def test_an_oversized_request_body_is_refused(self, client):
        response = client.post(
            "/api/v1/tools/call",
            content=b"x" * (3 * 1024 * 1024),
            headers={"Content-Type": "application/json"},
        )
        assert response.status_code == 413
        assert response.json()["error"]["code"] == "payload_too_large"


class TestDuplicateReview:
    def test_pending_candidates_are_listed_with_both_sides(self, client, seeded, db):
        with db.session_scope() as session:
            session.add(DuplicateCandidate(
                left_source_record_id=1, right_source_record_id=2,
                score=0.72, reasons={"duration": "differs"},
            ))
        rows = client.get("/api/v1/activities/duplicates").json()
        assert len(rows) == 1
        assert rows[0]["left"]["source"] == "garmin"
        assert rows[0]["score"] == 0.72

    def test_a_missing_candidate_is_a_typed_404(self, client, seeded):
        assert client.post("/api/v1/activities/duplicates/999",
                           params={"accept": True}).status_code == 404
