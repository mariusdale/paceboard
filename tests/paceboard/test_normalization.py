"""Provider payloads become correctly typed, correctly attributed rows."""

from __future__ import annotations

from datetime import date, datetime

import pytest
from sqlalchemy import select

from paceboard_api.db.models import (
    Athlete,
    BodyBatteryRecord,
    DailyHealth,
    Device,
    HeartRateZoneSet,
    HrvRecord,
    PerformanceMetric,
    SleepRecord,
    StressRecord,
    TrainingLoadRecord,
    TrainingStatusRecord,
)
from paceboard_api.ingest import normalize_garmin as norm
from paceboard_api.providers.dto import ProviderResult, ResultStatus
from paceboard_api.providers.garmin.provider import canonical_sport

from . import fixtures


def result(endpoint: str, data, params=None) -> ProviderResult:
    return ProviderResult(
        provider="garmin", endpoint=endpoint, params=params or {},
        status=ResultStatus.OK, data=data,
    )


class TestDailyHealth:
    def test_stats_populate_typed_columns(self, session):
        written = norm.daily_stats(
            session, result("get_stats", fixtures.GARMIN_STATS), None
        )
        assert written == 1
        row = session.execute(select(DailyHealth)).scalar_one()
        assert row.source == "garmin"
        assert row.day == date(2026, 8, 20)
        assert row.steps == 9124
        assert row.resting_hr == 48
        assert row.body_battery_high == 88
        assert row.avg_waking_respiration == pytest.approx(14.2)

    def test_repeated_normalization_updates_in_place(self, session):
        payload = result("get_stats", fixtures.GARMIN_STATS)
        norm.daily_stats(session, payload, None)
        norm.daily_stats(session, payload, None)
        assert len(session.execute(select(DailyHealth)).scalars().all()) == 1

    def test_a_second_tool_enriches_the_same_day_without_clobbering(self, session):
        norm.daily_stats(session, result("get_stats", fixtures.GARMIN_STATS), None)
        norm.heart_rate_summary(
            session,
            result("get_heart_rates_summary", {
                "date": "2026-08-20", "avg_heart_rate_bpm": 63.4,
                "resting_heart_rate_bpm": 48, "max_heart_rate_bpm": 152,
                "min_heart_rate_bpm": 44, "last_7_days_avg_resting_hr": 49,
            }),
            None,
        )
        row = session.execute(select(DailyHealth)).scalar_one()
        assert row.avg_hr == pytest.approx(63.4)
        assert row.steps == 9124, "the earlier tool's values must survive"

    def test_null_values_never_overwrite_an_existing_number(self, session):
        norm.daily_stats(session, result("get_stats", fixtures.GARMIN_STATS), None)
        sparse = {**fixtures.GARMIN_STATS, "resting_heart_rate_bpm": None}
        norm.daily_stats(session, result("get_stats", sparse), None)
        assert session.execute(select(DailyHealth)).scalar_one().resting_hr == 48

    def test_the_date_the_provider_reports_wins_over_the_date_requested(self, session):
        norm.daily_stats(
            session,
            result("get_stats", fixtures.GARMIN_STATS, {"date": "2026-08-21"}),
            None,
        )
        assert session.execute(select(DailyHealth)).scalar_one().day == date(2026, 8, 20)

    def test_request_date_is_used_when_the_payload_omits_one(self, session):
        payload = {k: v for k, v in fixtures.GARMIN_STRESS.items() if k != "date"}
        norm.stress_summary(
            session, result("get_stress_summary", payload, {"date": "2026-08-22"}), None
        )
        assert session.execute(select(StressRecord)).scalar_one().day == date(2026, 8, 22)


class TestSleep:
    def test_single_night(self, session):
        norm.sleep_summary(
            session,
            result("get_sleep_summary", fixtures.GARMIN_SLEEP_SUMMARY, {"date": "2026-08-20"}),
            None,
        )
        row = session.execute(select(SleepRecord)).scalar_one()
        assert row.total_sleep_s == 27180
        assert row.sleep_score == 82
        assert row.deep_s == 4980
        assert isinstance(row.sleep_start_utc, datetime)

    def test_epoch_milliseconds_become_datetimes(self, session):
        norm.sleep_summary(
            session,
            result("get_sleep_summary", fixtures.GARMIN_SLEEP_SUMMARY, {"date": "2026-08-20"}),
            None,
        )
        row = session.execute(select(SleepRecord)).scalar_one()
        assert row.sleep_start_utc.year == 2025 or row.sleep_start_utc.year == 2026
        assert row.sleep_end_utc > row.sleep_start_utc

    def test_range_writes_one_row_per_night(self, session):
        written = norm.sleep_range(
            session, result("get_sleep_summary_range", fixtures.GARMIN_SLEEP_RANGE), None
        )
        assert written == 2
        rows = session.execute(select(SleepRecord).order_by(SleepRecord.day)).scalars().all()
        assert [r.day for r in rows] == [date(2026, 8, 19), date(2026, 8, 20)]
        assert [r.sleep_score for r in rows] == [74, 82]


class TestTraining:
    def test_status_writes_both_status_and_load_rows(self, session):
        norm.training_status(
            session, result("get_training_status", fixtures.GARMIN_TRAINING_STATUS), None
        )
        status = session.execute(select(TrainingStatusRecord)).scalar_one()
        load = session.execute(select(TrainingLoadRecord)).scalar_one()
        assert status.status_label == "PRODUCTIVE"
        assert status.acwr == pytest.approx(1.08)
        assert load.acute_load == 412
        assert load.chronic_load == 380

    def test_load_trend_writes_one_row_per_day(self, session):
        written = norm.training_load_trend(
            session, result("get_training_load_trend", fixtures.GARMIN_LOAD_TREND), None
        )
        assert written == 3
        rows = session.execute(
            select(TrainingLoadRecord).order_by(TrainingLoadRecord.day)
        ).scalars().all()
        assert rows[-1].balance == -32
        assert rows[-1].vo2max == pytest.approx(52.3)

    def test_vo2max_trend_becomes_dated_performance_metrics(self, session):
        norm.vo2max_trend(
            session, result("get_vo2max_trend", fixtures.GARMIN_VO2MAX_TREND), None
        )
        rows = session.execute(
            select(PerformanceMetric).where(PerformanceMetric.metric == "vo2max")
            .order_by(PerformanceMetric.day)
        ).scalars().all()
        assert len(rows) == 2
        assert rows[-1].value == pytest.approx(52.3)
        assert rows[-1].sport == "running"
        assert rows[-1].units == "ml/kg/min"


class TestAccount:
    def test_profile_converts_grams_to_kilograms(self, session):
        norm.user_profile(
            session, result("get_user_profile", fixtures.GARMIN_USER_PROFILE), None
        )
        row = session.execute(select(Athlete)).scalar_one()
        assert row.weight_kg == pytest.approx(74.5)
        assert row.height_cm == pytest.approx(181.0)
        assert row.birth_date == date(1994, 4, 12)
        assert row.lactate_threshold_hr == 168

    def test_hr_zones_are_stored_per_sport(self, session):
        norm.hr_zones(
            session, result("get_heart_rate_zones", fixtures.GARMIN_HR_ZONE_CONFIG), None
        )
        row = session.execute(select(HeartRateZoneSet)).scalar_one()
        assert row.sport == "default"
        assert row.zone_floors == [93, 111, 130, 148, 167]
        assert row.max_hr == 190

    def test_devices_store_the_provider_id_as_a_string(self, session):
        norm.devices(session, result("get_devices", fixtures.GARMIN_DEVICES), None)
        row = session.execute(select(Device)).scalar_one()
        assert row.provider_id == "3312345678"
        assert isinstance(row.provider_id, str)

    def test_personal_records_mark_an_unreported_date(self, session):
        norm.personal_records(
            session, result("get_personal_record", fixtures.GARMIN_PERSONAL_RECORDS), None
        )
        rows = {
            r.metric: r
            for r in session.execute(select(PerformanceMetric)).scalars().all()
        }
        assert rows["pr:Fastest 1K"].context["date_known"] is False
        assert rows["pr:Longest Run"].context["date_known"] is True
        assert rows["pr:Longest Run"].day == date(2026, 5, 4)


class TestNoDataIsNotZero:
    def test_a_no_data_result_writes_nothing(self, session):
        empty = ProviderResult(
            provider="garmin", endpoint="get_stats", params={"date": "2026-08-20"},
            status=ResultStatus.NO_DATA, data=None,
            text=fixtures.GARMIN_TEXT_RESPONSES["no_readiness"],
        )
        assert norm.daily_stats(session, empty, None) == 0
        assert session.execute(select(DailyHealth)).first() is None

    def test_spo2_without_measurements_writes_no_row(self, session):
        assert norm.spo2(session, result("get_spo2_data", {"date": "2026-08-31"}), None) == 0
        assert session.execute(select(DailyHealth)).first() is None

    def test_body_battery_records_the_day_it_reports(self, session):
        norm.body_battery(
            session, result("get_body_battery", fixtures.GARMIN_BODY_BATTERY), None
        )
        row = session.execute(select(BodyBatteryRecord)).scalar_one()
        assert row.day == date(2026, 8, 20)
        assert row.charged == 62
        assert row.events


class TestHrv:
    def test_daily_hrv_carries_baseline_bounds(self, session):
        norm.hrv_daily(session, result("get_hrv_data", fixtures.GARMIN_HRV), None)
        row = session.execute(select(HrvRecord)).scalar_one()
        assert row.last_night_avg_ms == 71
        assert row.baseline_balanced_low_ms == 58
        assert row.status == "BALANCED"


class TestSportMapping:
    @pytest.mark.parametrize(
        "provider_type,expected",
        [("running", "run"), ("trail_running", "run"), ("treadmill_running", "run"),
         ("cycling", "ride"), ("gravel_cycling", "ride"), ("indoor_cycling", "ride"),
         ("lap_swimming", "swim"), ("strength_training", "strength"),
         ("hiking", "hike"), ("walking", "walk"), ("cross_country_skiing", "ski"),
         ("some_new_running_thing", "run"), ("underwater_basket_weaving", "other"),
         (None, "other")],
    )
    def test_garmin_types_collapse_onto_canonical_sports(self, provider_type, expected):
        assert canonical_sport(provider_type) == expected


class TestHandlerCoverage:
    def test_every_scheduled_tool_with_a_handler_has_one_registered(self):
        from paceboard_api.providers.garmin import catalog

        needed = {
            spec.handler for spec in catalog.SCHEDULED_TOOLS
            if spec.handler and spec.category != "activities"
        }
        registered = set(norm.handler_names())
        assert needed <= registered, f"missing handlers: {sorted(needed - registered)}"


def test_zero_readiness_is_a_real_score(session):
    norm.training_readiness(session, result('get_training_readiness', [{'date': '2026-08-20', 'score': 0, 'level': 'POOR'}]), None)
    assert session.execute(select(DailyHealth)).scalar_one().training_readiness == 0
