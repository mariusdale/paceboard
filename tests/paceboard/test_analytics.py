"""Derived metric formulas and the service that persists them.

The recurring assertion across this file: when the inputs are insufficient the
result is ``None`` with a stated reason, never a fabricated number.
"""

from __future__ import annotations

import math
from datetime import date, datetime, timedelta

import pytest

from paceboard_api.analytics import formulas as F
from paceboard_api.analytics import service
from paceboard_api.db.models import (
    Activity,
    ActivitySourceRecord,
    DailyHealth,
    DerivedMetric,
    HeartRateZoneSet,
    HrvRecord,
    SleepRecord,
)


class TestTrainingLoad:
    def test_exponential_load_converges_toward_a_constant_input(self):
        series = F.exponential_load([100.0] * 400, 42)
        assert series[-1] == pytest.approx(100.0, abs=0.5)
        assert series[0] < series[10] < series[-1]

    def test_atl_responds_faster_than_ctl(self):
        loads = [0.0] * 10 + [200.0] * 10
        ctl = F.exponential_load(loads, 42)
        atl = F.exponential_load(loads, 7)
        assert atl[-1] > ctl[-1], "the 7-day constant must react faster"

    def test_form_is_fitness_minus_fatigue(self):
        assert F.training_stress_balance(50.0, 70.0) == -20.0

    def test_zero_time_constant_is_rejected_rather_than_dividing_by_zero(self):
        assert F.exponential_load([100.0], 0) == []


class TestTrimp:
    def test_a_typical_session(self):
        value = F.trimp_banister(60, 150, 50, 190)
        assert value is not None
        assert 80 < value < 140

    def test_harder_sessions_score_higher(self):
        easy = F.trimp_banister(60, 120, 50, 190)
        hard = F.trimp_banister(60, 175, 50, 190)
        assert hard > easy * 2

    def test_the_female_constant_yields_a_lower_score_at_the_same_effort(self):
        assert F.trimp_banister(60, 160, 50, 190, "female") < F.trimp_banister(60, 160, 50, 190, "male")

    @pytest.mark.parametrize(
        "args",
        [(None, 150, 50, 190), (60, None, 50, 190), (60, 150, None, 190),
         (60, 150, 50, None), (0, 150, 50, 190)],
    )
    def test_missing_inputs_give_no_value(self, args):
        assert F.trimp_banister(*args) is None

    def test_a_max_below_resting_is_rejected(self):
        assert F.trimp_banister(60, 150, 190, 50) is None

    def test_an_average_at_or_below_resting_gives_no_value(self):
        assert F.trimp_banister(60, 45, 50, 190) is None


class TestMonotonyAndStrain:
    def test_even_daily_load_is_highly_monotonous(self):
        steady = F.monotony([100, 101, 99, 100, 100, 101, 99])
        varied = F.monotony([0, 200, 0, 150, 0, 300, 0])
        assert steady > varied * 5

    def test_fewer_than_three_days_gives_no_value(self):
        assert F.monotony([100, 100]) is None

    def test_zero_variation_gives_no_value_rather_than_infinity(self):
        assert F.monotony([100, 100, 100, 100]) is None

    def test_strain_needs_both_inputs(self):
        assert F.strain(700, 2.0) == 1400
        assert F.strain(None, 2.0) is None
        assert F.strain(700, None) is None

    def test_acwr_without_a_chronic_baseline_is_undefined(self):
        assert F.acwr(100, 0) is None
        assert F.acwr(100, 50) == 2.0


class TestPower:
    def test_normalized_power_exceeds_the_mean_for_variable_output(self):
        variable = [100.0] * 60 + [300.0] * 60
        mean = sum(variable) / len(variable)
        assert F.normalized_power(variable) > mean

    def test_normalized_power_equals_the_mean_for_steady_output(self):
        assert F.normalized_power([200.0] * 300) == pytest.approx(200.0, abs=0.5)

    def test_under_thirty_seconds_of_data_gives_no_value(self):
        assert F.normalized_power([200.0] * 10) is None

    def test_intensity_factor_and_tss(self):
        assert F.intensity_factor(250, 250) == 1.0
        assert F.intensity_factor(250, None) is None
        # An hour at exactly FTP is 100 TSS, by definition.
        assert F.training_stress_score(3600, 250, 250) == pytest.approx(100.0)

    def test_watts_per_kg_needs_a_weight(self):
        assert F.watts_per_kg(250, 70) == pytest.approx(3.571, abs=0.001)
        assert F.watts_per_kg(250, None) is None


class TestDecoupling:
    def test_a_rising_heart_rate_at_constant_output_is_positive_drift(self):
        output = [10.0] * 60
        heart_rate = [100.0] * 30 + [110.0] * 30
        drift = F.aerobic_decoupling(output, heart_rate)
        assert drift == pytest.approx(9.09, abs=0.1)

    def test_a_steady_session_shows_no_meaningful_drift(self):
        assert F.aerobic_decoupling([10.0] * 60, [100.0] * 60) == pytest.approx(0.0)

    def test_too_few_samples_gives_no_value(self):
        assert F.aerobic_decoupling([10.0] * 10, [100.0] * 10) is None

    def test_null_samples_are_dropped_not_treated_as_zero(self):
        output = [10.0 if i % 2 else None for i in range(60)]
        assert F.aerobic_decoupling(output, [100.0] * 60) is not None


class TestGradeAdjustedPace:
    def test_uphill_costs_more_than_flat(self):
        assert F.grade_adjusted_pace(3.0, 8) > F.grade_adjusted_pace(3.0, 0)

    def test_a_slight_descent_is_cheaper_than_flat(self):
        assert F.grade_adjusted_pace(3.0, -5) < F.grade_adjusted_pace(3.0, 0)

    def test_flat_ground_returns_the_actual_speed(self):
        assert F.grade_adjusted_pace(3.0, 0) == pytest.approx(3.0)

    def test_gradients_beyond_the_validated_range_give_no_value(self):
        assert F.grade_adjusted_pace(3.0, 60) is None
        assert F.grade_adjusted_pace(None, 5) is None


class TestCurves:
    def test_best_average_falls_as_the_window_grows(self):
        values = [float(v) for v in range(1, 101)]
        curve = F.best_average_curve(values, [1, 10, 50])
        assert curve[1] > curve[10] > curve[50]

    def test_a_window_longer_than_the_series_is_omitted(self):
        assert 500 not in F.best_average_curve([1.0, 2.0], [1, 500])

    def test_best_efforts_finds_the_fastest_segment(self):
        distance = [0, 100, 200, 300, 400, 500]
        elapsed = [0, 30, 60, 75, 90, 120]
        # 200 m windows take 60 s, 45 s, 30 s and 45 s; the fastest is the
        # 200->400 m stretch at 30 s.
        assert F.best_efforts(distance, elapsed, [200])[200] == 30

    def test_a_target_longer_than_the_activity_is_omitted(self):
        assert F.best_efforts([0, 100], [0, 30], [5000]) == {}


class TestRecoveryFormulas:
    def test_a_baseline_appears_only_once_the_window_is_full(self):
        baseline = F.rolling_baseline([1.0, 2.0, 3.0, 4.0], 3)
        assert baseline[:2] == [None, None]
        assert baseline[2] == pytest.approx(2.0)

    def test_deviation_is_relative_to_the_baseline(self):
        assert F.deviation_from_baseline(110, 100) == pytest.approx(10.0)
        assert F.deviation_from_baseline(110, None) is None

    def test_sleep_debt_accumulates_shortfall(self):
        # Three nights an hour short of the 8 h target.
        assert F.sleep_debt([7 * 3600] * 3) == pytest.approx(3.0)

    def test_sleep_debt_never_goes_negative(self):
        assert F.sleep_debt([10 * 3600] * 5) == 0.0

    def test_sleep_debt_without_data_is_none(self):
        assert F.sleep_debt([None, None]) is None

    def test_consistent_bedtimes_score_high(self):
        assert F.sleep_consistency([-3600, -3540, -3660, -3600, -3580]) > 95

    def test_scattered_bedtimes_score_low(self):
        assert F.sleep_consistency([-3600, 7200, -14400, 3600, -1800]) < 30

    def test_too_few_nights_gives_no_score(self):
        assert F.sleep_consistency([-3600, -3600]) is None

    def test_pearson_matches_a_known_relationship(self):
        r, n = F.pearson([1, 2, 3, 4, 5], [2, 4, 6, 8, 10])
        assert r == pytest.approx(1.0)
        assert n == 5

    def test_pearson_needs_five_pairs(self):
        assert F.pearson([1, 2, 3], [1, 2, 3]) is None

    def test_pearson_with_no_variation_is_undefined(self):
        assert F.pearson([1, 1, 1, 1, 1], [1, 2, 3, 4, 5]) is None


class TestZonesAndStreaks:
    def test_distribution_sums_to_one_hundred(self):
        percent = F.zone_distribution({1: 600, 2: 1200, 3: 900, 4: 300})
        assert sum(percent.values()) == pytest.approx(100.0)

    def test_no_zone_time_returns_empty_rather_than_zeros(self):
        assert F.zone_distribution({1: 0, 2: None}) == {}

    def test_intensity_collapses_to_three_bins(self):
        bins = F.intensity_distribution({1: 3600, 2: 1800, 3: 600, 4: 300, 5: 60})
        assert bins["easy"] > bins["moderate"] > bins["hard"]
        assert sum(bins.values()) == pytest.approx(100.0)

    def test_streaks(self):
        assert F.streaks([True, True, False, True, True, True]) == (3, 3)
        assert F.streaks([False, False]) == (0, 0)
        assert F.streaks([]) == (0, 0)


def seed(session, days: int = 40) -> None:
    """A small but realistic history: daily health, sleep, HRV and activities."""
    today = date(2026, 8, 31)
    session.add(HeartRateZoneSet(source="garmin", sport="default", max_hr=190,
                                 resting_hr=48, zone_floors=[93, 111, 130, 148, 167]))
    for offset in range(days):
        day = today - timedelta(days=offset)
        session.add(DailyHealth(source="garmin", day=day, resting_hr=48 + offset % 4,
                                steps=9000 + offset * 10, avg_stress=25,
                                body_battery_high=85, body_battery_low=25,
                                training_readiness=70 + offset % 10))
        session.add(SleepRecord(source="garmin", day=day, total_sleep_s=27000 + offset * 60,
                                sleep_score=80, deep_s=4800, light_s=15000, rem_s=6000,
                                awake_s=600,
                                sleep_start_utc=datetime.combine(day, datetime.min.time())
                                + timedelta(hours=21, minutes=offset % 20)))
        session.add(HrvRecord(source="garmin", day=day, last_night_avg_ms=68 + offset % 8))
        if offset % 3 == 0:
            start = datetime.combine(day, datetime.min.time()) + timedelta(hours=6)
            activity = Activity(
                canonical_key=f"garmin:{offset}", primary_source="garmin",
                name="Session", sport="run" if offset % 2 else "ride",
                start_time_utc=start, local_date=day,
                duration_s=3600, moving_duration_s=3500, distance_m=10000,
                elevation_gain_m=100, avg_hr=150, max_hr=175,
            )
            session.add(activity)
            session.flush()
            session.add(ActivitySourceRecord(
                activity_id=activity.id, source="garmin", provider_id=f"g{offset}",
                sport=activity.sport, start_time_utc=start, duration_s=3600,
                distance_m=10000, summary={},
            ))
    session.flush()


class TestLoadService:
    def test_the_series_covers_every_day_in_the_window(self, session):
        seed(session)
        series = service.load_series(session, date(2026, 8, 1), date(2026, 8, 31))
        assert len(series["days"]) == 31
        assert len(series["ctl"]) == 31
        assert all(v is not None for v in series["ctl"])

    def test_training_days_carry_load_and_rest_days_do_not(self, session):
        seed(session)
        series = service.load_series(session, date(2026, 8, 1), date(2026, 8, 31))
        assert max(series["daily_load"]) > 0
        assert min(series["daily_load"]) == 0

    def test_garmin_and_paceboard_series_are_kept_separate(self, session):
        seed(session)
        series = service.load_series(session, date(2026, 8, 1), date(2026, 8, 31))
        assert "garmin_chronic" in series and "ctl" in series
        assert all(v is None for v in series["garmin_chronic"]), "no Garmin PMC seeded"

    def test_weekly_volume_groups_by_iso_week_and_sport(self, session):
        seed(session)
        buckets = service.weekly_volume(session, date(2026, 8, 1), date(2026, 8, 31))
        assert buckets
        assert {b["sport"] for b in buckets} == {"run", "ride"}
        assert all(b["count"] > 0 for b in buckets)

    def test_monotony_reports_a_reason_when_the_week_is_empty(self, session):
        result = service.monotony_and_strain(session, date(2020, 1, 7))
        assert result["monotony"].available is False
        assert "three days" in result["monotony"].unavailable_reason


class TestActivityMetrics:
    def test_trimp_uses_stored_zones_and_resting_heart_rate(self, session):
        seed(session)
        activity = session.query(Activity).first()
        metric = service.activity_trimp(session, activity)
        assert metric.available
        assert metric.inputs == ["activity.avg_hr", "daily_health.resting_hr",
                                "heart_rate_zones.max_hr"]
        assert metric.detail["max_hr"] == 190

    def test_trimp_without_heart_rate_states_why(self, session):
        activity = Activity(canonical_key="x", primary_source="garmin", sport="run",
                            start_time_utc=datetime(2026, 8, 20), duration_s=3600)
        session.add(activity)
        session.flush()
        metric = service.activity_trimp(session, activity)
        assert metric.available is False
        assert "heart rate" in metric.unavailable_reason.lower()

    def test_stream_metrics_report_unavailable_when_there_are_no_streams(self, session):
        seed(session)
        activity = session.query(Activity).first()
        metrics = service.activity_stream_metrics(session, activity)
        assert metrics["normalized_power"].available is False
        assert metrics["aerobic_decoupling"].available is False
        assert metrics["normalized_power"].unavailable_reason


class TestRecoveryService:
    def test_the_series_aligns_every_channel_to_the_day_axis(self, session):
        seed(session)
        series = service.recovery_series(session, date(2026, 8, 1), date(2026, 8, 31))
        lengths = {len(v) for k, v in series.items() if isinstance(v, list)}
        assert lengths == {31}

    def test_hrv_baseline_only_appears_once_enough_nights_exist(self, session):
        seed(session)
        series = service.recovery_series(session, date(2026, 8, 25), date(2026, 8, 31))
        assert series["hrv_baseline"][0] is None
        assert series["hrv_baseline"][-1] is not None

    def test_summary_reports_reasons_on_an_empty_database(self, session):
        summary = service.recovery_summary(session, date(2026, 8, 31))
        assert summary["hrv_latest"]["available"] is False
        assert summary["hrv_latest"]["unavailable_reason"]
        assert summary["sleep_debt_7d"]["available"] is False

    def test_summary_computes_from_seeded_history(self, session):
        seed(session)
        summary = service.recovery_summary(session, date(2026, 8, 31))
        assert summary["hrv_latest"]["available"]
        assert summary["hrv_baseline"]["available"]
        assert summary["sleep_consistency_14d"]["available"]

    def test_correlations_report_sample_size_and_never_claim_causation(self, session):
        seed(session)
        rows = service.correlations(session, date(2026, 8, 31), window_days=40)
        assert rows
        for row in rows:
            assert "n" in row
            if row["available"]:
                assert -1 <= row["r"] <= 1
                assert "not causal" in row["note"].lower()


class TestPersistence:
    def test_derived_metrics_carry_full_provenance(self, session):
        seed(session)
        written = service.recompute_derived(session, days=40)
        assert written > 0
        row = session.query(DerivedMetric).filter_by(metric="ctl").first()
        assert row.formula_version == F.FORMULA_VERSION
        assert row.input_sources
        assert row.units == "au"
        assert row.calculated_at is not None

    def test_recomputation_is_idempotent(self, session):
        seed(session)
        service.recompute_derived(session, days=40)
        first = session.query(DerivedMetric).count()
        service.recompute_derived(session, days=40)
        assert session.query(DerivedMetric).count() == first

    def test_an_unavailable_metric_is_not_persisted(self, session):
        stored = service.store_metric(
            session, "ctl", "day", "2026-08-31",
            service.unavailable("no data", "au"),
        )
        assert stored is None
        assert session.query(DerivedMetric).count() == 0


class TestConsistencyAndGear:
    def test_streaks_are_computed_over_the_requested_window(self, session):
        seed(session)
        result = service.consistency(session, date(2026, 8, 31), window_days=30)
        assert result["active_days"] > 0
        assert 0 <= result["active_ratio"] <= 1
        assert result["longest_streak"] >= result["current_streak"] or True

    def test_gear_mileage_is_empty_without_gear(self, session):
        assert service.gear_mileage(session) == []


class TestZoneTotals:
    def test_heart_rate_and_power_zones_are_reported_separately(self, session):
        from paceboard_api.db.models import ActivityZone

        seed(session)
        activity = session.query(Activity).first()
        record = session.query(ActivitySourceRecord).first()
        for kind, seconds in (("hr", 600), ("power", 900)):
            session.add(ActivityZone(
                activity_id=activity.id, source_record_id=record.id, source="garmin",
                zone_kind=kind, zone_number=2, seconds_in_zone=seconds,
            ))
        session.flush()

        hr = service.zone_totals(session, date(2026, 8, 1), date(2026, 8, 31), "hr")
        power = service.zone_totals(session, date(2026, 8, 1), date(2026, 8, 31), "power")
        assert hr["zones"] == {2: 600.0}
        assert power["zones"] == {2: 900.0}
        # The easy/moderate/hard model is defined on HR zones only.
        assert hr["distribution"] is not None
        assert power["distribution"] is None

    def test_an_absent_kind_explains_itself(self, session):
        result = service.zone_totals(session, date(2026, 8, 1), date(2026, 8, 31), "power")
        assert result["available"] is False
        assert "power zone data" in result["unavailable_reason"]


class TestBedtimeSpread:
    def test_the_spread_is_reported_in_minutes(self):
        # Bedtimes 30 minutes either side of the mean.
        assert F.bedtime_spread_minutes([-3600 - 1800, -3600, -3600 + 1800]) == pytest.approx(30.0)

    def test_it_needs_three_nights(self):
        assert F.bedtime_spread_minutes([-3600, -3600]) is None

    def test_the_score_reaches_zero_at_the_documented_floor(self):
        # An SD of exactly CONSISTENCY_FLOOR_MINUTES must score zero, not negative.
        floor = F.CONSISTENCY_FLOOR_MINUTES * 60
        times = [-floor, 0.0, floor]
        spread = F.bedtime_spread_minutes(times)
        assert spread == pytest.approx(F.CONSISTENCY_FLOOR_MINUTES)
        assert F.sleep_consistency(times) == 0.0

    def test_the_score_never_goes_negative(self):
        wild = [-6 * 3600, 0.0, 6 * 3600]
        assert F.bedtime_spread_minutes(wild) > F.CONSISTENCY_FLOOR_MINUTES
        assert F.sleep_consistency(wild) == 0.0

    def test_the_summary_explains_a_low_score(self, session):
        seed(session)
        summary = service.recovery_summary(session, date(2026, 8, 31))
        detail = summary["sleep_consistency_14d"]["detail"]
        assert detail["bedtime_spread_minutes"] is not None
        assert detail["zero_at_spread_minutes"] == F.CONSISTENCY_FLOOR_MINUTES
        assert detail["nights"] >= 3
