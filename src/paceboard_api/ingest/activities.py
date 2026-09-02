"""Activity ingestion: source records, canonical merge, laps, zones, streams."""

from __future__ import annotations

import json
import zlib
from datetime import datetime
from typing import Any, Iterable, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db.models import (
    Activity,
    ActivityLap,
    ActivitySourceRecord,
    ActivitySplit,
    ActivityStream,
    ActivityZone,
    Gear,
)
from ..logging_conf import get_logger
from ..providers.dto import ActivitySummaryDTO, LapDTO, StreamSetDTO, ZoneDTO
from .upsert import apply_fields

log = get_logger("paceboard.ingest.activities")

#: Per-field preference when a canonical activity has several sources.
#: Garmin is the device-native record (physiology, sensor samples, training
#: effect); Strava owns its own social/segment metadata and its curated name.
FIELD_PREFERENCE: dict[str, tuple[str, ...]] = {
    "name": ("strava", "garmin"),
    "sport": ("garmin", "strava"),
    "provider_type": ("garmin", "strava"),
    "start_time_local": ("garmin", "strava"),
    "utc_offset_seconds": ("strava", "garmin"),
    "duration_s": ("garmin", "strava"),
    "moving_duration_s": ("strava", "garmin"),
    "elapsed_duration_s": ("strava", "garmin"),
    "distance_m": ("garmin", "strava"),
    "elevation_gain_m": ("garmin", "strava"),
    "elevation_loss_m": ("garmin", "strava"),
    "avg_speed_mps": ("garmin", "strava"),
    "max_speed_mps": ("garmin", "strava"),
    "avg_hr": ("garmin", "strava"),
    "max_hr": ("garmin", "strava"),
    "avg_cadence": ("garmin", "strava"),
    "avg_power_w": ("garmin", "strava"),
    "max_power_w": ("garmin", "strava"),
    "normalized_power_w": ("strava", "garmin"),
    "calories": ("garmin", "strava"),
    "training_load": ("garmin", "strava"),
    "aerobic_training_effect": ("garmin", "strava"),
    "anaerobic_training_effect": ("garmin", "strava"),
    "training_effect_label": ("garmin", "strava"),
    "perceived_effort": ("garmin", "strava"),
    "avg_temperature_c": ("garmin", "strava"),
    "device_name": ("garmin", "strava"),
    "start_lat": ("strava", "garmin"),
    "start_lng": ("strava", "garmin"),
}

STREAM_CHANNELS = (
    "time", "distance", "lat", "lng", "altitude", "velocity_smooth",
    "heartrate", "cadence", "watts", "temp", "moving", "grade_smooth",
)


def encode_stream(values: list[Optional[float]]) -> bytes:
    return zlib.compress(json.dumps(values).encode(), level=6)


def decode_stream(blob: Optional[bytes]) -> list[Optional[float]]:
    if not blob:
        return []
    return json.loads(zlib.decompress(blob).decode())


# -- source records --------------------------------------------------------


def upsert_source_record(
    session: Session, dto: ActivitySummaryDTO, *, raw_payload_id: Optional[int] = None
) -> ActivitySourceRecord:
    """Insert or update one provider's record for an activity."""
    row = session.execute(
        select(ActivitySourceRecord).where(
            ActivitySourceRecord.source == dto.source,
            ActivitySourceRecord.provider_id == dto.provider_id,
        )
    ).scalar_one_or_none()
    if row is None:
        row = ActivitySourceRecord(source=dto.source, provider_id=dto.provider_id)
        session.add(row)

    summary = dict(row.summary or {})
    summary.update(_dto_summary_fields(dto))
    apply_fields(
        row,
        {
            "external_id": dto.external_id,
            "upload_id": dto.upload_id,
            "name": dto.name,
            "sport": dto.sport,
            "provider_type": dto.provider_type,
            "start_time_utc": dto.start_time_utc,
            "start_time_local": dto.start_time_local,
            "utc_offset_seconds": dto.utc_offset_seconds,
            "duration_s": dto.duration_s,
            "distance_m": dto.distance_m,
            "raw_payload_id": raw_payload_id,
        },
    )
    row.summary = summary
    row.fetched_at = datetime.utcnow()
    session.flush()
    return row


def _dto_summary_fields(dto: ActivitySummaryDTO) -> dict[str, Any]:
    fields = {name: getattr(dto, name) for name in FIELD_PREFERENCE}
    fields["extra"] = dto.extra
    fields["gear_provider_id"] = dto.gear_provider_id
    return {k: v for k, v in fields.items() if v is not None}


def mark_detail_fetched(session: Session, row: ActivitySourceRecord, status: str) -> None:
    row.detail_status = status
    if row.activity_id:
        activity = session.get(Activity, row.activity_id)
        if activity is not None:
            activity.detail_status = status
    session.flush()


# -- canonical merge -------------------------------------------------------


def rebuild_canonical(session: Session, activity: Activity) -> Activity:
    """Recompute every canonical field from the linked source records.

    Runs after any source record changes, so the canonical row is always a pure
    function of its sources — which makes repeat syncs idempotent and makes the
    provenance map trustworthy.
    """
    # Query the source records rather than reading the relationship: a merge
    # that just re-pointed a record would otherwise be invisible behind a stale
    # identity-map collection.
    sources = list(
        session.execute(
            select(ActivitySourceRecord)
            .where(ActivitySourceRecord.activity_id == activity.id)
            .order_by(ActivitySourceRecord.id)
        ).scalars()
    )
    if not sources:
        return activity
    by_source = {row.source: row for row in sources}
    provenance: dict[str, str] = {}

    for field, order in FIELD_PREFERENCE.items():
        chosen_value, chosen_source = None, None
        for source in list(order) + [s.source for s in sources]:
            row = by_source.get(source)
            if row is None:
                continue
            value = (row.summary or {}).get(field)
            if value is not None:
                chosen_value, chosen_source = value, source
                break
        if chosen_value is not None:
            setattr(activity, field, chosen_value)
            provenance[field] = chosen_source or ""

    primary = "garmin" if "garmin" in by_source else sources[0].source
    primary_row = by_source[primary]
    activity.primary_source = primary
    activity.start_time_utc = primary_row.start_time_utc
    provenance["start_time_utc"] = primary
    if activity.start_time_local:
        try:
            activity.local_date = datetime.fromisoformat(
                str(activity.start_time_local)[:19]
            ).date()
        except ValueError:
            activity.local_date = activity.start_time_utc.date()
    else:
        activity.local_date = activity.start_time_utc.date()

    activity.has_gps = activity.start_lat is not None or any(
        session.execute(
            select(ActivityStream.id).where(
                ActivityStream.activity_id == activity.id,
                ActivityStream.channel == "lat",
            )
        ).scalars()
    )
    activity.has_streams = bool(
        session.execute(
            select(ActivityStream.id).where(ActivityStream.activity_id == activity.id)
        ).first()
    )
    activity.duplicate_state = "merged" if len(sources) > 1 else "single"
    activity.field_provenance = provenance

    gear_provider_id = next(
        (
            (row.summary or {}).get("gear_provider_id")
            for row in sources
            if (row.summary or {}).get("gear_provider_id")
        ),
        None,
    )
    if gear_provider_id:
        gear = session.execute(
            select(Gear).where(Gear.provider_id == str(gear_provider_id))
        ).scalar_one_or_none()
        if gear is not None:
            activity.gear_id = gear.id
    session.flush()
    # Drop the cached collection so later reads see the sources just recomputed.
    session.expire(activity, ["sources"])
    return activity


def ensure_canonical(session: Session, row: ActivitySourceRecord) -> Activity:
    """Attach a source record to a canonical activity, creating one if needed."""
    if row.activity_id:
        activity = session.get(Activity, row.activity_id)
        if activity is not None:
            return rebuild_canonical(session, activity)
    activity = Activity(
        canonical_key=f"{row.source}:{row.provider_id}",
        primary_source=row.source,
        sport=row.sport,
        start_time_utc=row.start_time_utc,
    )
    session.add(activity)
    session.flush()
    row.activity_id = activity.id
    session.flush()
    return rebuild_canonical(session, activity)


# -- child records ---------------------------------------------------------


def replace_laps(
    session: Session, row: ActivitySourceRecord, laps: Iterable[LapDTO]
) -> int:
    laps = list(laps)
    if not laps:
        return 0
    session.query(ActivityLap).filter(ActivityLap.source_record_id == row.id).delete()
    for lap in laps:
        session.add(
            ActivityLap(
                activity_id=row.activity_id,
                source_record_id=row.id,
                source=row.source,
                lap_index=lap.lap_index,
                start_time_utc=lap.start_time_utc,
                duration_s=lap.duration_s,
                moving_duration_s=lap.moving_duration_s,
                distance_m=lap.distance_m,
                avg_speed_mps=lap.avg_speed_mps,
                max_speed_mps=lap.max_speed_mps,
                avg_hr=lap.avg_hr,
                max_hr=lap.max_hr,
                avg_power_w=lap.avg_power_w,
                avg_cadence=lap.avg_cadence,
                elevation_gain_m=lap.elevation_gain_m,
                elevation_loss_m=lap.elevation_loss_m,
                calories=lap.calories,
                intensity_type=lap.intensity_type,
            )
        )
    session.flush()
    return len(laps)


def replace_zones(
    session: Session, row: ActivitySourceRecord, zones: Iterable[ZoneDTO]
) -> int:
    zones = [z for z in zones if z.zone_number]
    if not zones:
        return 0
    session.query(ActivityZone).filter(ActivityZone.source_record_id == row.id).delete()
    seen: set[tuple[str, int]] = set()
    for zone in zones:
        key = (zone.zone_kind, zone.zone_number)
        if key in seen:
            continue
        seen.add(key)
        session.add(
            ActivityZone(
                activity_id=row.activity_id,
                source_record_id=row.id,
                source=row.source,
                zone_kind=zone.zone_kind,
                zone_number=zone.zone_number,
                seconds_in_zone=zone.seconds_in_zone,
                low_boundary=zone.low_boundary,
                high_boundary=zone.high_boundary,
            )
        )
    session.flush()
    return len(seen)


def replace_splits(
    session: Session,
    row: ActivitySourceRecord,
    split_type: str,
    entries: list[dict[str, Any]],
) -> int:
    if not entries:
        return 0
    session.query(ActivitySplit).filter(
        ActivitySplit.source_record_id == row.id,
        ActivitySplit.split_type == split_type,
    ).delete()
    for index, entry in enumerate(entries, start=1):
        session.add(
            ActivitySplit(
                activity_id=row.activity_id,
                source_record_id=row.id,
                source=row.source,
                split_type=split_type,
                split_index=index,
                distance_m=_f(entry.get("distance") or entry.get("distance_meters")),
                duration_s=_f(entry.get("duration") or entry.get("duration_seconds")
                              or entry.get("elapsedDuration")),
                elevation_gain_m=_f(entry.get("elevationGain")
                                    or entry.get("elevation_gain_meters")),
                avg_speed_mps=_f(entry.get("averageSpeed") or entry.get("avg_speed_mps")),
                avg_hr=_f(entry.get("averageHR") or entry.get("avg_hr_bpm")),
                details=entry,
            )
        )
    session.flush()
    return len(entries)


def _f(value: Any) -> Optional[float]:
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def replace_streams(
    session: Session, row: ActivitySourceRecord, streams: Optional[StreamSetDTO]
) -> int:
    if streams is None or not streams.channels:
        return 0
    session.query(ActivityStream).filter(
        ActivityStream.source_record_id == row.id
    ).delete()
    written = 0
    for channel, values in streams.channels.items():
        if channel not in STREAM_CHANNELS or not any(v is not None for v in values):
            continue
        session.add(
            ActivityStream(
                activity_id=row.activity_id,
                source_record_id=row.id,
                source=row.source,
                channel=channel,
                units=streams.units.get(channel),
                point_count=len(values),
                data=encode_stream(values),
            )
        )
        written += 1
    session.flush()
    return written


def load_streams(
    session: Session, activity_id: int, channels: Optional[list[str]] = None
) -> dict[str, dict[str, Any]]:
    """Read decoded streams for one activity, preferring the canonical source."""
    activity = session.get(Activity, activity_id)
    preferred = activity.primary_source if activity else "garmin"
    stmt = select(ActivityStream).where(ActivityStream.activity_id == activity_id)
    if channels:
        stmt = stmt.where(ActivityStream.channel.in_(channels))
    rows = list(session.execute(stmt).scalars())
    out: dict[str, dict[str, Any]] = {}
    for row in rows:
        existing = out.get(row.channel)
        if existing is not None and existing["source"] == preferred:
            continue
        out[row.channel] = {
            "source": row.source,
            "units": row.units,
            "point_count": row.point_count,
            "data": decode_stream(row.data),
        }
    return out
