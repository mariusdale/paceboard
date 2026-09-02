"""Cross-provider deduplication: match, merge, review, and never lose data."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from sqlalchemy import select

from paceboard_api.db.models import Activity, ActivitySourceRecord, DuplicateCandidate
from paceboard_api.ingest import activities as act
from paceboard_api.ingest.dedupe import (
    AUTO_MERGE_SCORE,
    REVIEW_SCORE,
    link_source_record,
    resolve_candidate,
    score_pair,
    sports_compatible,
)
from paceboard_api.providers.dto import ActivitySummaryDTO

BASE = datetime(2026, 8, 20, 5, 32, 11)


def dto(source, provider_id, **overrides) -> ActivitySummaryDTO:
    values = dict(
        source=source, provider_id=provider_id, name="Morning Run", sport="run",
        provider_type="running" if source == "garmin" else "Run",
        start_time_utc=BASE, duration_s=3180.0, distance_m=10120.0,
    )
    values.update(overrides)
    return ActivitySummaryDTO(**values)


def add(session, summary) -> ActivitySourceRecord:
    return act.upsert_source_record(session, summary)


class TestScoring:
    def test_identical_sessions_from_two_providers_auto_merge(self, session, settings):
        left = add(session, dto("garmin", "g1"))
        right = add(session, dto("strava", "s1", start_time_utc=BASE + timedelta(seconds=45),
                                 distance_m=10118.0, duration_s=3200.0))
        match = score_pair(left, right, settings)
        assert match.score >= AUTO_MERGE_SCORE
        assert match.decision == "auto"

    def test_an_explicit_provider_link_is_decisive(self, session, settings):
        left = add(session, dto("garmin", "24188138095"))
        right = add(session, dto("strava", "s1",
                                 start_time_utc=BASE + timedelta(seconds=200),
                                 external_id="garmin_push_24188138095",
                                 distance_m=99999.0, duration_s=99999.0))
        match = score_pair(left, right, settings)
        assert match.score == 1.0
        assert "external_id" in match.reasons["explicit_link"]

    def test_a_shared_upload_id_is_decisive(self, session, settings):
        left = add(session, dto("garmin", "g1", upload_id="u-42"))
        right = add(session, dto("strava", "s1", upload_id="u-42",
                                 start_time_utc=BASE + timedelta(seconds=120)))
        assert score_pair(left, right, settings).score == 1.0

    def test_two_records_from_the_same_provider_never_match(self, session, settings):
        left = add(session, dto("garmin", "g1"))
        right = add(session, dto("garmin", "g2"))
        match = score_pair(left, right, settings)
        assert match.score == 0.0
        assert "same provider" in match.reasons["rejected"]

    def test_incompatible_sports_are_rejected_outright(self, session, settings):
        left = add(session, dto("garmin", "g1", sport="run"))
        right = add(session, dto("strava", "s1", sport="swim"))
        assert score_pair(left, right, settings).score == 0.0

    def test_starts_beyond_the_tolerance_are_rejected(self, session, settings):
        left = add(session, dto("garmin", "g1"))
        right = add(session, dto("strava", "s1", start_time_utc=BASE + timedelta(hours=2)))
        match = score_pair(left, right, settings)
        assert match.score == 0.0
        assert "start times differ" in match.reasons["rejected"]

    def test_elapsed_versus_moving_time_lands_in_review_not_auto_merge(
        self, session, settings
    ):
        """The classic real-world case: Strava reports elapsed, Garmin moving."""
        left = add(session, dto("garmin", "g1", distance_m=10120.0, duration_s=3180.0))
        right = add(session, dto("strava", "s1", start_time_utc=BASE + timedelta(seconds=60),
                                 distance_m=10118.0, duration_s=3600.0))
        match = score_pair(left, right, settings)
        assert REVIEW_SCORE <= match.score < AUTO_MERGE_SCORE
        assert match.decision == "review"
        assert "differs" in match.reasons["duration"]
        assert match.reasons["distance"] == "within tolerance"

    def test_a_genuinely_different_session_is_rejected(self, session, settings):
        left = add(session, dto("garmin", "g1", distance_m=10120.0, duration_s=3180.0))
        right = add(session, dto("strava", "s1", start_time_utc=BASE + timedelta(seconds=200),
                                 distance_m=4000.0, duration_s=1200.0))
        match = score_pair(left, right, settings)
        assert match.decision == "reject"

    def test_missing_measurements_are_not_treated_as_a_mismatch(self, session, settings):
        left = add(session, dto("garmin", "g1", distance_m=None, duration_s=None))
        right = add(session, dto("strava", "s1", start_time_utc=BASE + timedelta(seconds=10)))
        match = score_pair(left, right, settings)
        assert match.reasons["distance"] == "not comparable"
        assert match.score >= REVIEW_SCORE

    @pytest.mark.parametrize(
        "left,right,expected",
        [("run", "run", True), ("run", "hike", True), ("run", "walk", True),
         ("ride", "other", True), ("run", "ride", False), ("swim", "ride", False)],
    )
    def test_sport_compatibility(self, left, right, expected):
        assert sports_compatible(left, right) is expected


class TestMerging:
    def test_an_auto_match_produces_one_canonical_activity_with_two_sources(
        self, session, settings
    ):
        garmin = add(session, dto("garmin", "g1"))
        link_source_record(session, garmin, settings)
        strava = add(session, dto("strava", "s1", start_time_utc=BASE + timedelta(seconds=45)))
        activity, pending = link_source_record(session, strava, settings)

        assert pending is None
        assert len(session.execute(select(Activity)).scalars().all()) == 1
        assert {s.source for s in activity.sources} == {"garmin", "strava"}
        assert activity.duplicate_state == "merged"

    def test_both_source_records_survive_a_merge(self, session, settings):
        garmin = add(session, dto("garmin", "g1"))
        link_source_record(session, garmin, settings)
        strava = add(session, dto("strava", "s1", start_time_utc=BASE + timedelta(seconds=45)))
        link_source_record(session, strava, settings)

        rows = session.execute(select(ActivitySourceRecord)).scalars().all()
        assert len(rows) == 2
        assert all(row.activity_id is not None for row in rows)

    def test_the_canonical_row_records_where_each_value_came_from(self, session, settings):
        garmin = add(session, dto("garmin", "g1", distance_m=10120.0, avg_hr=148.0))
        link_source_record(session, garmin, settings)
        strava = add(session, dto("strava", "s1", start_time_utc=BASE + timedelta(seconds=45),
                                  name="Sunrise 10k", distance_m=10118.0,
                                  moving_duration_s=3140.0))
        activity, _ = link_source_record(session, strava, settings)

        provenance = activity.field_provenance
        assert provenance["distance_m"] == "garmin", "device-native distance wins"
        assert provenance["avg_hr"] == "garmin"
        assert provenance["name"] == "strava", "the Strava title is the one the user edits"
        assert activity.name == "Sunrise 10k"
        assert activity.distance_m == pytest.approx(10120.0)

    def test_garmin_becomes_the_primary_source(self, session, settings):
        strava = add(session, dto("strava", "s1"))
        link_source_record(session, strava, settings)
        garmin = add(session, dto("garmin", "g1", start_time_utc=BASE + timedelta(seconds=20)))
        activity, _ = link_source_record(session, garmin, settings)
        assert activity.primary_source == "garmin"

    def test_an_unmatched_activity_stays_single(self, session, settings):
        garmin = add(session, dto("garmin", "g1"))
        activity, pending = link_source_record(session, garmin, settings)
        assert pending is None
        assert activity.duplicate_state == "single"
        assert len(activity.sources) == 1


class TestReviewQueue:
    def test_an_uncertain_pair_is_queued_rather_than_merged(self, session, settings):
        garmin = add(session, dto("garmin", "g1", distance_m=10120.0, duration_s=3180.0))
        link_source_record(session, garmin, settings)
        strava = add(session, dto("strava", "s1", start_time_utc=BASE + timedelta(seconds=60),
                                  distance_m=10118.0, duration_s=3600.0))
        activity, pending = link_source_record(session, strava, settings)

        assert pending is not None
        assert pending.state == "pending"
        assert len(session.execute(select(Activity)).scalars().all()) == 2
        assert activity.duplicate_state == "single"

    def test_confirming_a_candidate_merges_it(self, session, settings):
        garmin = add(session, dto("garmin", "g1", distance_m=10120.0, duration_s=3180.0))
        link_source_record(session, garmin, settings)
        strava = add(session, dto("strava", "s1", start_time_utc=BASE + timedelta(seconds=60),
                                  distance_m=10118.0, duration_s=3600.0))
        _, pending = link_source_record(session, strava, settings)

        merged = resolve_candidate(session, pending.id, accept=True)
        assert merged is not None
        assert {s.source for s in merged.sources} == {"garmin", "strava"}
        assert session.get(DuplicateCandidate, pending.id).state == "confirmed"

    def test_rejecting_a_candidate_keeps_two_activities(self, session, settings):
        garmin = add(session, dto("garmin", "g1", distance_m=10120.0, duration_s=3180.0))
        link_source_record(session, garmin, settings)
        strava = add(session, dto("strava", "s1", start_time_utc=BASE + timedelta(seconds=60),
                                  distance_m=10118.0, duration_s=3600.0))
        _, pending = link_source_record(session, strava, settings)

        assert resolve_candidate(session, pending.id, accept=False) is None
        assert session.get(DuplicateCandidate, pending.id).state == "rejected"
        assert len(session.execute(select(Activity)).scalars().all()) == 2

    def test_a_candidate_is_not_duplicated_across_repeated_syncs(self, session, settings):
        garmin = add(session, dto("garmin", "g1", distance_m=10120.0, duration_s=3180.0))
        link_source_record(session, garmin, settings)
        summary = dto("strava", "s1", start_time_utc=BASE + timedelta(seconds=60),
                      distance_m=10118.0, duration_s=3600.0)
        for _ in range(3):
            link_source_record(session, add(session, summary), settings)
        assert len(session.execute(select(DuplicateCandidate)).scalars().all()) == 1


class TestTolerancesAreConfigurable:
    def test_a_wider_start_tolerance_admits_a_further_apart_pair(
        self, session, settings, monkeypatch
    ):
        left = add(session, dto("garmin", "g1"))
        right = add(session, dto("strava", "s1", start_time_utc=BASE + timedelta(minutes=9)))
        assert score_pair(left, right, settings).score == 0.0

        import dataclasses

        widened = dataclasses.replace(settings, dedupe_start_tolerance_seconds=1200)
        assert score_pair(left, right, widened).score > 0
