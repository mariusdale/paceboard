"""Development fixture data — clearly labelled, never enabled by default.

Fixture mode exists so the dashboard's end-to-end test can run without a Garmin
account, and so the UI can be worked on offline. It is guarded three ways:

* ``PACEBOARD_FIXTURE_MODE=true`` must be set explicitly;
* every row it writes is stamped with ``source="fixture"``, so nothing here can
  be mistaken for measured data anywhere in the app;
* ``GET /api/v1/status`` reports ``fixture_mode: true`` and the dashboard shows a
  persistent banner while it is on.

Never point fixture mode at a database holding real data: :func:`seed` refuses to
run when measured rows are already present.
"""

from __future__ import annotations

import math
import random
from datetime import date, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .db.models import (
    Activity,
    ActivityLap,
    ActivitySourceRecord,
    ActivityStream,
    ActivityZone,
    Athlete,
    BodyBatteryRecord,
    DailyHealth,
    Gear,
    HeartRateZoneSet,
    HrvRecord,
    PerformanceMetric,
    ProviderCapability,
    ProviderConnection,
    RawPayload,
    SleepRecord,
    StressRecord,
    SyncRun,
    SyncWatermark,
    TrainingLoadRecord,
    TrainingStatusRecord,
)
from .ingest.activities import encode_stream
from .logging_conf import get_logger

log = get_logger("paceboard.fixtures")

SOURCE = "fixture"
DAYS = 90


class FixtureRefused(RuntimeError):
    """Raised when the target database already holds measured data."""


def seed(session: Session, days: int = DAYS, anchor: date | None = None) -> dict[str, int]:
    """Populate a database with labelled synthetic data. Idempotent."""
    real = session.execute(
        select(func.count()).select_from(ActivitySourceRecord)
        .where(ActivitySourceRecord.source != SOURCE)
    ).scalar_one()
    if real:
        raise FixtureRefused(
            f"Refusing to seed fixtures: the database already holds {real} real "
            f"activity records. Point PACEBOARD_DATABASE_PATH at a scratch file."
        )
    if session.execute(
        select(func.count()).select_from(ActivitySourceRecord)
        .where(ActivitySourceRecord.source == SOURCE)
    ).scalar_one():
        log.info("Fixture data already present; nothing to seed")
        return {"skipped": 1}

    rng = random.Random(20260902)
    today = anchor or date.today()
    written: dict[str, int] = {}

    session.add(Athlete(
        source=SOURCE, provider_id="fixture-athlete", display_name="Fixture Athlete",
        sex="MALE", birth_date=date(1994, 4, 12), height_cm=181.0, weight_kg=74.5,
        measurement_system="metric", vo2max_running=52.0, lactate_threshold_hr=168,
    ))
    session.add(HeartRateZoneSet(
        source=SOURCE, sport="default", method="HR_RESERVE", resting_hr=48,
        max_hr=190, lactate_threshold_hr=168, zone_floors=[93, 111, 130, 148, 167],
    ))
    shoes = Gear(source=SOURCE, provider_id="fixture-shoes", name="Fixture Trainers",
                 gear_type="shoes", provider_distance_m=402_000)
    session.add(shoes)
    session.flush()

    for provider, endpoint, status in (
        (SOURCE, "get_stats", "available"),
        (SOURCE, "get_sleep_summary", "available"),
        (SOURCE, "get_running_tolerance", "available"),
    ):
        session.add(ProviderCapability(
            provider=provider, name=endpoint, category="daily_health", scope="daily",
            cadence="daily", enabled=True, status=status, handler="daily_stats",
            description="Synthetic capability (fixture mode)",
            last_status="unsupported" if endpoint == "get_running_tolerance" else "ok",
            call_count=days,
        ))
    # Deliberately NOT "connected": fixture data comes from this seeder, not from
    # a Garmin MCP session, and claiming otherwise would be exactly the kind of
    # fabricated state fixture mode exists to avoid.
    session.add(ProviderConnection(
        provider="garmin", status="disconnected", display_name=None,
        endpoint=None, last_checked_at=datetime.utcnow(),
        last_error="Fixture mode: no Garmin MCP session was established.",
        details={"read_only": True},
    ))
    session.add(SyncWatermark(
        provider=SOURCE, category="sync", key="", cursor_date=today,
        cursor_time=datetime.utcnow(), last_success_at=datetime.utcnow(),
        last_status="ok",
    ))

    activity_count = 0
    for offset in range(days):
        day = today - timedelta(days=days - 1 - offset)
        phase = offset / 7 * math.pi
        session.add(DailyHealth(
            source=SOURCE, day=day,
            steps=8000 + int(2500 * math.sin(phase)) + rng.randint(-500, 500),
            step_goal=10000, distance_m=7000 + rng.randint(-800, 800),
            total_calories=2800 + rng.randint(-200, 200),
            active_calories=550 + rng.randint(-150, 300),
            moderate_intensity_minutes=rng.randint(10, 45),
            vigorous_intensity_minutes=rng.randint(0, 25),
            intensity_minutes_goal=150,
            resting_hr=47 + int(2 * math.sin(phase)) + rng.randint(0, 2),
            min_hr=42, max_hr=150 + rng.randint(0, 30),
            rhr_7day_avg=48, avg_stress=24 + rng.randint(-6, 14),
            max_stress=70 + rng.randint(0, 25),
            body_battery_high=80 + rng.randint(-12, 18),
            body_battery_low=20 + rng.randint(-8, 15),
            body_battery_charged=55 + rng.randint(-10, 15),
            body_battery_drained=50 + rng.randint(-10, 20),
            avg_waking_respiration=14.0 + rng.random(),
            spo2_avg=96.0 + rng.random(),
            training_readiness=68 + rng.randint(-18, 22),
            readiness_level="MODERATE",
        ))
        bedtime = datetime.combine(day, datetime.min.time()) - timedelta(hours=2, minutes=rng.randint(0, 50))
        total_sleep = 25200 + rng.randint(-4000, 5000)
        session.add(SleepRecord(
            source=SOURCE, day=day, sleep_start_utc=bedtime,
            sleep_end_utc=bedtime + timedelta(seconds=total_sleep),
            total_sleep_s=total_sleep, deep_s=int(total_sleep * 0.18),
            light_s=int(total_sleep * 0.55), rem_s=int(total_sleep * 0.22),
            awake_s=int(total_sleep * 0.05), awake_count=rng.randint(0, 3),
            sleep_score=72 + rng.randint(-16, 22), score_qualifier="GOOD",
            avg_overnight_hrv=66.0 + 8 * math.sin(phase) + rng.randint(-4, 4),
        ))
        session.add(HrvRecord(
            source=SOURCE, day=day,
            last_night_avg_ms=66.0 + 8 * math.sin(phase) + rng.randint(-5, 5),
            weekly_avg_ms=66.0, baseline_balanced_low_ms=56.0,
            baseline_balanced_upper_ms=80.0, status="BALANCED",
        ))
        session.add(StressRecord(
            source=SOURCE, day=day, avg_stress=24 + rng.randint(-6, 14),
            max_stress=78, rest_pct=40.0, low_pct=32.0, medium_pct=21.0, high_pct=7.0,
            data_points=960,
        ))
        session.add(BodyBatteryRecord(
            source=SOURCE, day=day, charged=55 + rng.randint(-10, 15),
            drained=50 + rng.randint(-10, 20), highest=80 + rng.randint(-12, 18),
            lowest=20 + rng.randint(-8, 15), level_label="HIGH",
        ))
        chronic = 300 + offset * 1.4
        acute = chronic * (0.9 + 0.25 * math.sin(phase))
        session.add(TrainingLoadRecord(
            source=SOURCE, day=day, acute_load=round(acute, 1),
            chronic_load=round(chronic, 1), balance=round(chronic - acute, 1),
            acwr=round(acute / chronic, 2), acwr_status="OPTIMAL",
            optimal_min=280.0, optimal_max=520.0, training_status="PRODUCTIVE",
            vo2max=51.0 + offset * 0.01,
        ))
        if offset % 7 == 0:
            session.add(TrainingStatusRecord(
                source=SOURCE, day=day, status_code=3, status_label="PRODUCTIVE",
                feedback="Fixture training status", fitness_trend=1,
                acwr=round(acute / chronic, 2), acwr_status="OPTIMAL",
                load_aerobic_low=210.0, load_aerobic_high=95.0, load_anaerobic=32.0,
            ))
            session.add(PerformanceMetric(
                source=SOURCE, metric="vo2max", sport="running", day=day,
                value=round(51.0 + offset * 0.01, 1), units="ml/kg/min",
            ))

        # Roughly four sessions a week.
        if offset % 7 in (0, 2, 4, 5):
            activity_count += 1
            _add_activity(session, day, offset, shoes.id, rng)

    session.add(RawPayload(
        provider=SOURCE, endpoint="get_stats", params={"date": today.isoformat()},
        params_hash="fixture-stats", status="ok", content_type="json",
        content_json={"note": "Synthetic fixture payload", "total_steps": 9000},
        byte_size=64, duration_ms=12, retrieved_at=datetime.utcnow(),
    ))
    session.add(RawPayload(
        provider=SOURCE, endpoint="get_running_tolerance", params={"date": today.isoformat()},
        params_hash="fixture-tolerance", status="unsupported", content_type="text",
        content_text="Your device does not support this metric.",
        byte_size=42, duration_ms=8, retrieved_at=datetime.utcnow(),
    ))
    session.add(SyncRun(
        providers=SOURCE, mode="backfill", categories="account,activities,daily_health,training",
        status="success", trigger="fixture",
        started_at=datetime.utcnow() - timedelta(minutes=4),
        finished_at=datetime.utcnow() - timedelta(minutes=1),
        range_start=today - timedelta(days=days - 1), range_end=today,
        tasks_total=5, tasks_done=5, records_written=days * 6, errors_count=0,
        summary={"tasks": [{"name": "daily", "provider": SOURCE, "status": "ok",
                            "records": days * 5, "calls": days, "notes": []}]},
    ))
    session.flush()

    written["activities"] = activity_count
    written["days"] = days
    log.warning(
        "Seeded FIXTURE data — every row is labelled source='fixture'",
        extra={"days": days, "activities": activity_count},
    )
    return written


def _add_activity(session: Session, day: date, offset: int, gear_id: int, rng) -> None:
    sport, distance, duration, name = (
        ("run", 10000 + rng.randint(-3000, 8000), 3300 + rng.randint(-600, 2400), "Fixture Run")
        if offset % 2
        else ("ride", 34000 + rng.randint(-9000, 22000), 4800 + rng.randint(-900, 3000), "Fixture Ride")
    )
    start = datetime.combine(day, datetime.min.time()) + timedelta(hours=6, minutes=rng.randint(0, 200))
    avg_hr = 138 + rng.randint(-14, 22)
    activity = Activity(
        canonical_key=f"fixture:{offset}", primary_source=SOURCE, name=name,
        sport=sport, provider_type=sport, start_time_utc=start,
        start_time_local=(start + timedelta(hours=2)).isoformat(),
        utc_offset_seconds=7200, local_date=day,
        duration_s=float(duration), moving_duration_s=float(duration - 60),
        elapsed_duration_s=float(duration + 40), distance_m=float(distance),
        elevation_gain_m=float(rng.randint(40, 420)),
        elevation_loss_m=float(rng.randint(40, 420)),
        avg_speed_mps=distance / duration, max_speed_mps=distance / duration * 1.5,
        avg_hr=float(avg_hr), max_hr=float(avg_hr + rng.randint(12, 32)),
        avg_cadence=float(rng.randint(78, 92)),
        calories=float(rng.randint(400, 1100)),
        training_load=float(rng.randint(50, 190)),
        aerobic_training_effect=round(2.0 + rng.random() * 2, 1),
        anaerobic_training_effect=round(rng.random() * 1.5, 1),
        training_effect_label="TEMPO", avg_temperature_c=float(rng.randint(6, 24)),
        device_name="Fixture Device", gear_id=gear_id if sport == "run" else None,
        has_gps=True, has_streams=True, detail_status="complete",
        stream_status="complete", duplicate_state="single",
        field_provenance={"distance_m": SOURCE, "avg_hr": SOURCE},
    )
    session.add(activity)
    session.flush()

    record = ActivitySourceRecord(
        activity_id=activity.id, source=SOURCE, provider_id=f"fixture-{offset}",
        name=name, sport=sport, provider_type=sport, start_time_utc=start,
        duration_s=float(duration), distance_m=float(distance),
        detail_status="complete", fetched_at=datetime.utcnow(),
        summary={"distance_m": float(distance), "avg_hr": float(avg_hr)},
    )
    session.add(record)
    session.flush()

    laps = max(2, min(8, distance // 5000))
    for index in range(1, int(laps) + 1):
        session.add(ActivityLap(
            activity_id=activity.id, source_record_id=record.id, source=SOURCE,
            lap_index=index, start_time_utc=start + timedelta(seconds=duration // laps * (index - 1)),
            duration_s=duration / laps, moving_duration_s=duration / laps - 5,
            distance_m=distance / laps, avg_speed_mps=distance / duration,
            max_speed_mps=distance / duration * 1.3,
            avg_hr=float(avg_hr + rng.randint(-6, 8)),
            max_hr=float(avg_hr + rng.randint(10, 26)),
            elevation_gain_m=float(rng.randint(5, 70)), intensity_type="ACTIVE",
        ))

    for zone, seconds in enumerate(
        [duration * 0.15, duration * 0.35, duration * 0.32, duration * 0.14, duration * 0.04], 1
    ):
        session.add(ActivityZone(
            activity_id=activity.id, source_record_id=record.id, source=SOURCE,
            zone_kind="hr", zone_number=zone, seconds_in_zone=round(seconds, 1),
            low_boundary=[93, 111, 130, 148, 167][zone - 1],
        ))

    points = 240
    step = duration / points
    channels = {
        "time": [round(i * step, 1) for i in range(points)],
        "distance": [round(distance * i / points, 1) for i in range(points)],
        "heartrate": [float(avg_hr + 14 * math.sin(i / 18) + rng.randint(-4, 4))
                      for i in range(points)],
        "velocity_smooth": [round(distance / duration * (1 + 0.22 * math.sin(i / 12)), 3)
                            for i in range(points)],
        "altitude": [round(40 + 55 * math.sin(i / 30), 1) for i in range(points)],
        "cadence": [float(84 + rng.randint(-5, 5)) for _ in range(points)],
        "lat": [round(59.913 + i * 0.00022 + 0.0009 * math.sin(i / 15), 6)
                for i in range(points)],
        "lng": [round(10.752 + i * 0.00034 + 0.0012 * math.cos(i / 15), 6)
                for i in range(points)],
    }
    if sport == "ride":
        channels["watts"] = [float(170 + 70 * math.sin(i / 10) + rng.randint(-18, 18))
                             for i in range(points)]
    units = {"time": "s", "distance": "m", "heartrate": "bpm", "velocity_smooth": "m/s",
             "altitude": "m", "cadence": "rpm", "lat": "deg", "lng": "deg", "watts": "W"}
    for channel, values in channels.items():
        session.add(ActivityStream(
            activity_id=activity.id, source_record_id=record.id, source=SOURCE,
            channel=channel, units=units.get(channel), point_count=len(values),
            data=encode_stream(values),
        ))
