"""SQLAlchemy 2.x ORM models — the normalized Paceboard store.

Design rules that apply throughout:

* Provider identifiers are stored as **strings**, never integers. Garmin
  activity ids exceed 2^53 and Strava ids are opaque.
* Every row carries source attribution (``source`` = ``garmin`` | ``strava`` |
  ``paceboard``) so a value can always be traced back to who produced it.
* Timestamps are UTC-naive ``DateTime`` columns (SQLite has no tz type); the
  matching ``*_local`` string and ``*_offset_seconds`` integer preserve what the
  provider reported locally.
* Natural keys get unique constraints so ingestion can upsert and repeat syncs
  stay idempotent.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Optional

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    JSON,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    """Declarative base with a JSON-friendly type map."""

    type_annotation_map = {dict[str, Any]: JSON, list[Any]: JSON}


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )


# ---------------------------------------------------------------------------
# Provider plumbing
# ---------------------------------------------------------------------------


class ProviderConnection(Base, TimestampMixin):
    """One row per provider describing whether Paceboard can reach it."""

    __tablename__ = "provider_connections"

    id: Mapped[int] = mapped_column(primary_key=True)
    provider: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="disconnected", nullable=False)
    display_name: Mapped[Optional[str]] = mapped_column(String(255))
    external_id: Mapped[Optional[str]] = mapped_column(String(64))
    endpoint: Mapped[Optional[str]] = mapped_column(String(512))
    scopes: Mapped[Optional[str]] = mapped_column(String(512))
    last_checked_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    last_success_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    last_error: Mapped[Optional[str]] = mapped_column(Text)
    details: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON)


class ProviderCapability(Base, TimestampMixin):
    """Capability catalog: what each provider can actually deliver here.

    Populated by discovery (MCP ``tools/list`` for Garmin, a static endpoint
    catalog for Strava) and reconciled against Paceboard's configured mapping,
    so an absent tool is recorded as ``unavailable`` rather than assumed.
    """

    __tablename__ = "provider_capabilities"
    __table_args__ = (
        UniqueConstraint("provider", "name", name="uq_capability_provider_name"),
        Index("ix_capability_status", "provider", "status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    category: Mapped[str] = mapped_column(String(64), default="other", nullable=False)
    scope: Mapped[str] = mapped_column(String(32), default="daily", nullable=False)
    cadence: Mapped[str] = mapped_column(String(32), default="daily", nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="unknown", nullable=False)
    handler: Mapped[Optional[str]] = mapped_column(String(64))
    description: Mapped[Optional[str]] = mapped_column(Text)
    expected_arguments: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON)
    input_schema: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON)
    last_called_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    last_status: Mapped[Optional[str]] = mapped_column(String(32))
    last_note: Mapped[Optional[str]] = mapped_column(Text)
    call_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)


class SyncRun(Base, TimestampMixin):
    __tablename__ = "sync_runs"
    __table_args__ = (Index("ix_sync_runs_started", "started_at"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    providers: Mapped[str] = mapped_column(String(128), nullable=False)
    mode: Mapped[str] = mapped_column(String(32), default="incremental", nullable=False)
    categories: Mapped[Optional[str]] = mapped_column(String(512))
    status: Mapped[str] = mapped_column(String(32), default="running", nullable=False)
    trigger: Mapped[str] = mapped_column(String(32), default="manual", nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    range_start: Mapped[Optional[date]] = mapped_column(Date)
    range_end: Mapped[Optional[date]] = mapped_column(Date)
    tasks_total: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    tasks_done: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    records_written: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    errors_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    cancel_requested: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    current_step: Mapped[Optional[str]] = mapped_column(String(255))
    summary: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON)

    # Named ``error_records`` rather than ``errors`` so it does not collide with
    # the API schema's own ``errors`` field during ORM validation.
    error_records: Mapped[list["SyncError"]] = relationship(
        back_populates="run", cascade="all, delete-orphan"
    )


class SyncError(Base):
    __tablename__ = "sync_errors"
    __table_args__ = (Index("ix_sync_errors_run", "sync_run_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    sync_run_id: Mapped[int] = mapped_column(ForeignKey("sync_runs.id", ondelete="CASCADE"))
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    capability: Mapped[Optional[str]] = mapped_column(String(128))
    kind: Mapped[str] = mapped_column(String(48), default="error", nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    context: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON)

    run: Mapped[SyncRun] = relationship(back_populates="error_records")


class SyncWatermark(Base, TimestampMixin):
    """Per-provider/per-category cursor so incremental syncs resume correctly."""

    __tablename__ = "sync_watermarks"
    __table_args__ = (
        UniqueConstraint("provider", "category", "key", name="uq_watermark"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    category: Mapped[str] = mapped_column(String(64), nullable=False)
    key: Mapped[str] = mapped_column(String(128), default="", nullable=False)
    cursor_date: Mapped[Optional[date]] = mapped_column(Date)
    cursor_time: Mapped[Optional[datetime]] = mapped_column(DateTime)
    cursor_value: Mapped[Optional[str]] = mapped_column(String(255))
    last_success_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    last_status: Mapped[Optional[str]] = mapped_column(String(32))


class RawPayload(Base):
    """Verbatim provider responses, kept forever and never silently discarded.

    ``content_json`` holds parsed JSON when the response was JSON; ``content_text``
    holds the literal text otherwise (Garmin MCP "No data" / error strings). The
    pair ``(provider, endpoint, params_hash)`` is unique so re-syncing the same
    window replaces rather than accumulates.
    """

    __tablename__ = "raw_payloads"
    __table_args__ = (
        UniqueConstraint("provider", "endpoint", "params_hash", name="uq_raw_payload"),
        Index("ix_raw_payload_retrieved", "provider", "retrieved_at"),
        Index("ix_raw_payload_ref", "reference_kind", "reference_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    endpoint: Mapped[str] = mapped_column(String(128), nullable=False)
    params: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON)
    params_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    schema_version: Mapped[str] = mapped_column(String(16), default="1", nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="ok", nullable=False)
    content_type: Mapped[str] = mapped_column(String(16), default="json", nullable=False)
    content_json: Mapped[Optional[Any]] = mapped_column(JSON)
    content_text: Mapped[Optional[str]] = mapped_column(Text)
    byte_size: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    duration_ms: Mapped[Optional[int]] = mapped_column(Integer)
    retrieved_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    sync_run_id: Mapped[Optional[int]] = mapped_column(Integer)
    reference_kind: Mapped[Optional[str]] = mapped_column(String(32))
    reference_id: Mapped[Optional[str]] = mapped_column(String(64))


# ---------------------------------------------------------------------------
# Identity / equipment
# ---------------------------------------------------------------------------


class Athlete(Base, TimestampMixin):
    __tablename__ = "athletes"
    __table_args__ = (UniqueConstraint("source", "provider_id", name="uq_athlete_source"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    provider_id: Mapped[str] = mapped_column(String(64), nullable=False)
    display_name: Mapped[Optional[str]] = mapped_column(String(255))
    sex: Mapped[Optional[str]] = mapped_column(String(16))
    birth_date: Mapped[Optional[date]] = mapped_column(Date)
    height_cm: Mapped[Optional[float]] = mapped_column(Float)
    weight_kg: Mapped[Optional[float]] = mapped_column(Float)
    measurement_system: Mapped[Optional[str]] = mapped_column(String(16))
    vo2max_running: Mapped[Optional[float]] = mapped_column(Float)
    vo2max_cycling: Mapped[Optional[float]] = mapped_column(Float)
    lactate_threshold_hr: Mapped[Optional[int]] = mapped_column(Integer)
    lactate_threshold_speed_mps: Mapped[Optional[float]] = mapped_column(Float)
    ftp_watts: Mapped[Optional[int]] = mapped_column(Integer)
    timezone: Mapped[Optional[str]] = mapped_column(String(64))
    raw_payload_id: Mapped[Optional[int]] = mapped_column(Integer)


class HeartRateZoneSet(Base, TimestampMixin):
    __tablename__ = "heart_rate_zones"
    __table_args__ = (UniqueConstraint("source", "sport", name="uq_hr_zone_sport"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    sport: Mapped[str] = mapped_column(String(32), default="default", nullable=False)
    method: Mapped[Optional[str]] = mapped_column(String(48))
    resting_hr: Mapped[Optional[int]] = mapped_column(Integer)
    max_hr: Mapped[Optional[int]] = mapped_column(Integer)
    lactate_threshold_hr: Mapped[Optional[int]] = mapped_column(Integer)
    zone_floors: Mapped[Optional[list[Any]]] = mapped_column(JSON)


class Device(Base, TimestampMixin):
    __tablename__ = "devices"
    __table_args__ = (UniqueConstraint("source", "provider_id", name="uq_device_source"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    provider_id: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[Optional[str]] = mapped_column(String(255))
    model: Mapped[Optional[str]] = mapped_column(String(255))
    serial_number: Mapped[Optional[str]] = mapped_column(String(128))
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    last_used_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    details: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON)


class Gear(Base, TimestampMixin):
    __tablename__ = "gear"
    __table_args__ = (UniqueConstraint("source", "provider_id", name="uq_gear_source"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    provider_id: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[Optional[str]] = mapped_column(String(255))
    brand: Mapped[Optional[str]] = mapped_column(String(128))
    model: Mapped[Optional[str]] = mapped_column(String(128))
    gear_type: Mapped[Optional[str]] = mapped_column(String(64))
    retired: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    provider_distance_m: Mapped[Optional[float]] = mapped_column(Float)
    details: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON)


# ---------------------------------------------------------------------------
# Activities
# ---------------------------------------------------------------------------


class Activity(Base, TimestampMixin):
    """Canonical activity — one row per real-world session.

    Populated by merging one or more :class:`ActivitySourceRecord` rows. Every
    merged field records where it came from in ``field_provenance``.
    """

    __tablename__ = "activities"
    __table_args__ = (
        Index("ix_activities_start", "start_time_utc"),
        Index("ix_activities_sport", "sport", "start_time_utc"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    canonical_key: Mapped[str] = mapped_column(String(80), unique=True, nullable=False)
    primary_source: Mapped[str] = mapped_column(String(32), nullable=False)
    name: Mapped[Optional[str]] = mapped_column(String(512))
    sport: Mapped[str] = mapped_column(String(48), default="other", nullable=False)
    sub_sport: Mapped[Optional[str]] = mapped_column(String(48))
    provider_type: Mapped[Optional[str]] = mapped_column(String(64))
    start_time_utc: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    start_time_local: Mapped[Optional[str]] = mapped_column(String(32))
    utc_offset_seconds: Mapped[Optional[int]] = mapped_column(Integer)
    local_date: Mapped[Optional[date]] = mapped_column(Date)

    duration_s: Mapped[Optional[float]] = mapped_column(Float)
    moving_duration_s: Mapped[Optional[float]] = mapped_column(Float)
    elapsed_duration_s: Mapped[Optional[float]] = mapped_column(Float)
    distance_m: Mapped[Optional[float]] = mapped_column(Float)
    elevation_gain_m: Mapped[Optional[float]] = mapped_column(Float)
    elevation_loss_m: Mapped[Optional[float]] = mapped_column(Float)
    avg_speed_mps: Mapped[Optional[float]] = mapped_column(Float)
    max_speed_mps: Mapped[Optional[float]] = mapped_column(Float)
    avg_hr: Mapped[Optional[float]] = mapped_column(Float)
    max_hr: Mapped[Optional[float]] = mapped_column(Float)
    avg_cadence: Mapped[Optional[float]] = mapped_column(Float)
    avg_power_w: Mapped[Optional[float]] = mapped_column(Float)
    max_power_w: Mapped[Optional[float]] = mapped_column(Float)
    normalized_power_w: Mapped[Optional[float]] = mapped_column(Float)
    calories: Mapped[Optional[float]] = mapped_column(Float)
    training_load: Mapped[Optional[float]] = mapped_column(Float)
    aerobic_training_effect: Mapped[Optional[float]] = mapped_column(Float)
    anaerobic_training_effect: Mapped[Optional[float]] = mapped_column(Float)
    training_effect_label: Mapped[Optional[str]] = mapped_column(String(64))
    perceived_effort: Mapped[Optional[float]] = mapped_column(Float)
    avg_temperature_c: Mapped[Optional[float]] = mapped_column(Float)
    device_name: Mapped[Optional[str]] = mapped_column(String(255))
    gear_id: Mapped[Optional[int]] = mapped_column(ForeignKey("gear.id"))

    start_lat: Mapped[Optional[float]] = mapped_column(Float)
    start_lng: Mapped[Optional[float]] = mapped_column(Float)
    has_gps: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    has_streams: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    detail_status: Mapped[str] = mapped_column(String(24), default="pending", nullable=False)
    stream_status: Mapped[str] = mapped_column(String(24), default="pending", nullable=False)

    field_provenance: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON)
    duplicate_state: Mapped[str] = mapped_column(String(24), default="single", nullable=False)

    sources: Mapped[list["ActivitySourceRecord"]] = relationship(
        back_populates="activity", cascade="all, delete-orphan", lazy="selectin"
    )


class ActivitySourceRecord(Base, TimestampMixin):
    """One provider's view of an activity. Never merged away, never deleted."""

    __tablename__ = "activity_source_records"
    __table_args__ = (
        UniqueConstraint("source", "provider_id", name="uq_source_record"),
        Index("ix_source_record_activity", "activity_id"),
        Index("ix_source_record_start", "source", "start_time_utc"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    activity_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("activities.id", ondelete="SET NULL")
    )
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    provider_id: Mapped[str] = mapped_column(String(64), nullable=False)
    external_id: Mapped[Optional[str]] = mapped_column(String(128))
    upload_id: Mapped[Optional[str]] = mapped_column(String(128))
    name: Mapped[Optional[str]] = mapped_column(String(512))
    sport: Mapped[str] = mapped_column(String(48), default="other", nullable=False)
    provider_type: Mapped[Optional[str]] = mapped_column(String(64))
    start_time_utc: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    start_time_local: Mapped[Optional[str]] = mapped_column(String(32))
    utc_offset_seconds: Mapped[Optional[int]] = mapped_column(Integer)
    duration_s: Mapped[Optional[float]] = mapped_column(Float)
    distance_m: Mapped[Optional[float]] = mapped_column(Float)
    summary: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON)
    detail_status: Mapped[str] = mapped_column(String(24), default="pending", nullable=False)
    raw_payload_id: Mapped[Optional[int]] = mapped_column(Integer)
    fetched_at: Mapped[Optional[datetime]] = mapped_column(DateTime)

    activity: Mapped[Optional[Activity]] = relationship(back_populates="sources")


class ActivityLap(Base):
    __tablename__ = "activity_laps"
    __table_args__ = (
        UniqueConstraint("source_record_id", "lap_index", name="uq_lap"),
        Index("ix_lap_activity", "activity_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    activity_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("activities.id", ondelete="CASCADE")
    )
    source_record_id: Mapped[int] = mapped_column(
        ForeignKey("activity_source_records.id", ondelete="CASCADE")
    )
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    lap_index: Mapped[int] = mapped_column(Integer, nullable=False)
    start_time_utc: Mapped[Optional[datetime]] = mapped_column(DateTime)
    duration_s: Mapped[Optional[float]] = mapped_column(Float)
    moving_duration_s: Mapped[Optional[float]] = mapped_column(Float)
    distance_m: Mapped[Optional[float]] = mapped_column(Float)
    avg_speed_mps: Mapped[Optional[float]] = mapped_column(Float)
    max_speed_mps: Mapped[Optional[float]] = mapped_column(Float)
    avg_hr: Mapped[Optional[float]] = mapped_column(Float)
    max_hr: Mapped[Optional[float]] = mapped_column(Float)
    avg_power_w: Mapped[Optional[float]] = mapped_column(Float)
    avg_cadence: Mapped[Optional[float]] = mapped_column(Float)
    elevation_gain_m: Mapped[Optional[float]] = mapped_column(Float)
    elevation_loss_m: Mapped[Optional[float]] = mapped_column(Float)
    calories: Mapped[Optional[float]] = mapped_column(Float)
    intensity_type: Mapped[Optional[str]] = mapped_column(String(32))


class ActivitySplit(Base):
    """Typed splits (climb/descent/interval segments) as reported by a provider."""

    __tablename__ = "activity_splits"
    __table_args__ = (
        UniqueConstraint("source_record_id", "split_type", "split_index", name="uq_split"),
        Index("ix_split_activity", "activity_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    activity_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("activities.id", ondelete="CASCADE")
    )
    source_record_id: Mapped[int] = mapped_column(
        ForeignKey("activity_source_records.id", ondelete="CASCADE")
    )
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    split_type: Mapped[str] = mapped_column(String(48), default="split", nullable=False)
    split_index: Mapped[int] = mapped_column(Integer, nullable=False)
    distance_m: Mapped[Optional[float]] = mapped_column(Float)
    duration_s: Mapped[Optional[float]] = mapped_column(Float)
    elevation_gain_m: Mapped[Optional[float]] = mapped_column(Float)
    avg_speed_mps: Mapped[Optional[float]] = mapped_column(Float)
    avg_hr: Mapped[Optional[float]] = mapped_column(Float)
    details: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON)


class ActivityZone(Base):
    __tablename__ = "activity_zones"
    __table_args__ = (
        UniqueConstraint("source_record_id", "zone_kind", "zone_number", name="uq_zone"),
        Index("ix_zone_activity", "activity_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    activity_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("activities.id", ondelete="CASCADE")
    )
    source_record_id: Mapped[int] = mapped_column(
        ForeignKey("activity_source_records.id", ondelete="CASCADE")
    )
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    zone_kind: Mapped[str] = mapped_column(String(16), default="hr", nullable=False)
    zone_number: Mapped[int] = mapped_column(Integer, nullable=False)
    seconds_in_zone: Mapped[Optional[float]] = mapped_column(Float)
    low_boundary: Mapped[Optional[float]] = mapped_column(Float)
    high_boundary: Mapped[Optional[float]] = mapped_column(Float)


class ActivityStream(Base):
    """Per-sample series, stored zlib-compressed as a JSON array of floats/nulls.

    One row per channel keeps reads cheap: the detail view fetches only the
    channels it charts, and a stream the provider never returned simply has no
    row (rendered as "Unavailable" rather than zero).
    """

    __tablename__ = "activity_streams"
    __table_args__ = (
        UniqueConstraint("source_record_id", "channel", name="uq_stream_channel"),
        Index("ix_stream_activity", "activity_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    activity_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("activities.id", ondelete="CASCADE")
    )
    source_record_id: Mapped[int] = mapped_column(
        ForeignKey("activity_source_records.id", ondelete="CASCADE")
    )
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    channel: Mapped[str] = mapped_column(String(32), nullable=False)
    units: Mapped[Optional[str]] = mapped_column(String(24))
    point_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    encoding: Mapped[str] = mapped_column(String(24), default="zlib-json", nullable=False)
    data: Mapped[Optional[bytes]] = mapped_column(LargeBinary)


class DuplicateCandidate(Base, TimestampMixin):
    """An uncertain cross-provider match awaiting a human decision."""

    __tablename__ = "duplicate_candidates"
    __table_args__ = (
        UniqueConstraint("left_source_record_id", "right_source_record_id", name="uq_dupe_pair"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    left_source_record_id: Mapped[int] = mapped_column(
        ForeignKey("activity_source_records.id", ondelete="CASCADE")
    )
    right_source_record_id: Mapped[int] = mapped_column(
        ForeignKey("activity_source_records.id", ondelete="CASCADE")
    )
    score: Mapped[float] = mapped_column(Float, nullable=False)
    reasons: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON)
    state: Mapped[str] = mapped_column(String(24), default="pending", nullable=False)
    decided_at: Mapped[Optional[datetime]] = mapped_column(DateTime)


# ---------------------------------------------------------------------------
# Daily health
# ---------------------------------------------------------------------------


class DailyHealth(Base, TimestampMixin):
    __tablename__ = "daily_health"
    __table_args__ = (
        UniqueConstraint("source", "day", name="uq_daily_health"),
        Index("ix_daily_health_day", "day"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    day: Mapped[date] = mapped_column(Date, nullable=False)
    steps: Mapped[Optional[int]] = mapped_column(Integer)
    step_goal: Mapped[Optional[int]] = mapped_column(Integer)
    distance_m: Mapped[Optional[float]] = mapped_column(Float)
    floors_ascended: Mapped[Optional[float]] = mapped_column(Float)
    total_calories: Mapped[Optional[float]] = mapped_column(Float)
    active_calories: Mapped[Optional[float]] = mapped_column(Float)
    bmr_calories: Mapped[Optional[float]] = mapped_column(Float)
    moderate_intensity_minutes: Mapped[Optional[int]] = mapped_column(Integer)
    vigorous_intensity_minutes: Mapped[Optional[int]] = mapped_column(Integer)
    intensity_minutes_goal: Mapped[Optional[int]] = mapped_column(Integer)
    resting_hr: Mapped[Optional[int]] = mapped_column(Integer)
    min_hr: Mapped[Optional[int]] = mapped_column(Integer)
    max_hr: Mapped[Optional[int]] = mapped_column(Integer)
    avg_hr: Mapped[Optional[float]] = mapped_column(Float)
    rhr_7day_avg: Mapped[Optional[int]] = mapped_column(Integer)
    avg_stress: Mapped[Optional[int]] = mapped_column(Integer)
    max_stress: Mapped[Optional[int]] = mapped_column(Integer)
    body_battery_high: Mapped[Optional[int]] = mapped_column(Integer)
    body_battery_low: Mapped[Optional[int]] = mapped_column(Integer)
    body_battery_charged: Mapped[Optional[int]] = mapped_column(Integer)
    body_battery_drained: Mapped[Optional[int]] = mapped_column(Integer)
    avg_waking_respiration: Mapped[Optional[float]] = mapped_column(Float)
    lowest_respiration: Mapped[Optional[float]] = mapped_column(Float)
    highest_respiration: Mapped[Optional[float]] = mapped_column(Float)
    avg_sleep_respiration: Mapped[Optional[float]] = mapped_column(Float)
    spo2_avg: Mapped[Optional[float]] = mapped_column(Float)
    spo2_lowest: Mapped[Optional[float]] = mapped_column(Float)
    sleeping_seconds: Mapped[Optional[int]] = mapped_column(Integer)
    training_readiness: Mapped[Optional[int]] = mapped_column(Integer)
    readiness_level: Mapped[Optional[str]] = mapped_column(String(48))
    readiness_factors: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON)
    raw_payload_id: Mapped[Optional[int]] = mapped_column(Integer)


class SleepRecord(Base, TimestampMixin):
    __tablename__ = "sleep_records"
    __table_args__ = (
        UniqueConstraint("source", "day", name="uq_sleep_day"),
        Index("ix_sleep_day", "day"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    day: Mapped[date] = mapped_column(Date, nullable=False)
    sleep_start_utc: Mapped[Optional[datetime]] = mapped_column(DateTime)
    sleep_end_utc: Mapped[Optional[datetime]] = mapped_column(DateTime)
    total_sleep_s: Mapped[Optional[int]] = mapped_column(Integer)
    nap_s: Mapped[Optional[int]] = mapped_column(Integer)
    deep_s: Mapped[Optional[int]] = mapped_column(Integer)
    light_s: Mapped[Optional[int]] = mapped_column(Integer)
    rem_s: Mapped[Optional[int]] = mapped_column(Integer)
    awake_s: Mapped[Optional[int]] = mapped_column(Integer)
    awake_count: Mapped[Optional[int]] = mapped_column(Integer)
    sleep_score: Mapped[Optional[int]] = mapped_column(Integer)
    score_qualifier: Mapped[Optional[str]] = mapped_column(String(48))
    avg_sleep_stress: Mapped[Optional[float]] = mapped_column(Float)
    avg_overnight_hrv: Mapped[Optional[float]] = mapped_column(Float)
    raw_payload_id: Mapped[Optional[int]] = mapped_column(Integer)


class HrvRecord(Base, TimestampMixin):
    __tablename__ = "hrv_records"
    __table_args__ = (UniqueConstraint("source", "day", name="uq_hrv_day"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    day: Mapped[date] = mapped_column(Date, nullable=False)
    last_night_avg_ms: Mapped[Optional[float]] = mapped_column(Float)
    last_night_5min_high_ms: Mapped[Optional[float]] = mapped_column(Float)
    weekly_avg_ms: Mapped[Optional[float]] = mapped_column(Float)
    baseline_low_ms: Mapped[Optional[float]] = mapped_column(Float)
    baseline_balanced_low_ms: Mapped[Optional[float]] = mapped_column(Float)
    baseline_balanced_upper_ms: Mapped[Optional[float]] = mapped_column(Float)
    status: Mapped[Optional[str]] = mapped_column(String(48))
    feedback: Mapped[Optional[str]] = mapped_column(Text)
    raw_payload_id: Mapped[Optional[int]] = mapped_column(Integer)


class StressRecord(Base, TimestampMixin):
    __tablename__ = "stress_records"
    __table_args__ = (UniqueConstraint("source", "day", name="uq_stress_day"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    day: Mapped[date] = mapped_column(Date, nullable=False)
    avg_stress: Mapped[Optional[int]] = mapped_column(Integer)
    max_stress: Mapped[Optional[int]] = mapped_column(Integer)
    rest_pct: Mapped[Optional[float]] = mapped_column(Float)
    low_pct: Mapped[Optional[float]] = mapped_column(Float)
    medium_pct: Mapped[Optional[float]] = mapped_column(Float)
    high_pct: Mapped[Optional[float]] = mapped_column(Float)
    data_points: Mapped[Optional[int]] = mapped_column(Integer)
    raw_payload_id: Mapped[Optional[int]] = mapped_column(Integer)


class BodyBatteryRecord(Base, TimestampMixin):
    __tablename__ = "body_battery_records"
    __table_args__ = (UniqueConstraint("source", "day", name="uq_bb_day"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    day: Mapped[date] = mapped_column(Date, nullable=False)
    charged: Mapped[Optional[int]] = mapped_column(Integer)
    drained: Mapped[Optional[int]] = mapped_column(Integer)
    highest: Mapped[Optional[int]] = mapped_column(Integer)
    lowest: Mapped[Optional[int]] = mapped_column(Integer)
    level_label: Mapped[Optional[str]] = mapped_column(String(48))
    feedback: Mapped[Optional[str]] = mapped_column(Text)
    events: Mapped[Optional[list[Any]]] = mapped_column(JSON)
    raw_payload_id: Mapped[Optional[int]] = mapped_column(Integer)


class BodyComposition(Base, TimestampMixin):
    __tablename__ = "body_composition"
    __table_args__ = (UniqueConstraint("source", "day", name="uq_body_comp_day"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    day: Mapped[date] = mapped_column(Date, nullable=False)
    weight_kg: Mapped[Optional[float]] = mapped_column(Float)
    bmi: Mapped[Optional[float]] = mapped_column(Float)
    body_fat_pct: Mapped[Optional[float]] = mapped_column(Float)
    body_water_pct: Mapped[Optional[float]] = mapped_column(Float)
    bone_mass_kg: Mapped[Optional[float]] = mapped_column(Float)
    muscle_mass_kg: Mapped[Optional[float]] = mapped_column(Float)
    raw_payload_id: Mapped[Optional[int]] = mapped_column(Integer)


# ---------------------------------------------------------------------------
# Training & performance
# ---------------------------------------------------------------------------


class TrainingStatusRecord(Base, TimestampMixin):
    __tablename__ = "training_status"
    __table_args__ = (UniqueConstraint("source", "day", name="uq_training_status_day"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    day: Mapped[date] = mapped_column(Date, nullable=False)
    status_code: Mapped[Optional[int]] = mapped_column(Integer)
    status_label: Mapped[Optional[str]] = mapped_column(String(64))
    feedback: Mapped[Optional[str]] = mapped_column(Text)
    fitness_trend: Mapped[Optional[int]] = mapped_column(Integer)
    acwr: Mapped[Optional[float]] = mapped_column(Float)
    acwr_status: Mapped[Optional[str]] = mapped_column(String(48))
    load_aerobic_low: Mapped[Optional[float]] = mapped_column(Float)
    load_aerobic_high: Mapped[Optional[float]] = mapped_column(Float)
    load_anaerobic: Mapped[Optional[float]] = mapped_column(Float)
    balance_feedback: Mapped[Optional[str]] = mapped_column(Text)
    raw_payload_id: Mapped[Optional[int]] = mapped_column(Integer)


class TrainingLoadRecord(Base, TimestampMixin):
    """Provider-reported PMC values (Garmin acute/chronic load, ACWR)."""

    __tablename__ = "training_load"
    __table_args__ = (
        UniqueConstraint("source", "day", name="uq_training_load_day"),
        Index("ix_training_load_day", "day"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    day: Mapped[date] = mapped_column(Date, nullable=False)
    acute_load: Mapped[Optional[float]] = mapped_column(Float)
    chronic_load: Mapped[Optional[float]] = mapped_column(Float)
    balance: Mapped[Optional[float]] = mapped_column(Float)
    acwr: Mapped[Optional[float]] = mapped_column(Float)
    acwr_status: Mapped[Optional[str]] = mapped_column(String(48))
    optimal_min: Mapped[Optional[float]] = mapped_column(Float)
    optimal_max: Mapped[Optional[float]] = mapped_column(Float)
    training_status: Mapped[Optional[str]] = mapped_column(String(64))
    vo2max: Mapped[Optional[float]] = mapped_column(Float)
    raw_payload_id: Mapped[Optional[int]] = mapped_column(Integer)


class PerformanceMetric(Base, TimestampMixin):
    """Sparse, dated scalar metrics: VO2 max, FTP, endurance score, PRs, ..."""

    __tablename__ = "performance_metrics"
    __table_args__ = (
        UniqueConstraint("source", "metric", "sport", "day", name="uq_performance_metric"),
        Index("ix_performance_metric", "metric", "day"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    metric: Mapped[str] = mapped_column(String(64), nullable=False)
    sport: Mapped[str] = mapped_column(String(32), default="generic", nullable=False)
    day: Mapped[date] = mapped_column(Date, nullable=False)
    value: Mapped[Optional[float]] = mapped_column(Float)
    text_value: Mapped[Optional[str]] = mapped_column(String(255))
    units: Mapped[Optional[str]] = mapped_column(String(32))
    context: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON)
    raw_payload_id: Mapped[Optional[int]] = mapped_column(Integer)


class DerivedMetric(Base, TimestampMixin):
    """Anything Paceboard computes itself, with full calculation provenance."""

    __tablename__ = "derived_metrics"
    __table_args__ = (
        UniqueConstraint("metric", "scope", "scope_key", name="uq_derived_metric"),
        Index("ix_derived_metric_scope", "metric", "scope"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    metric: Mapped[str] = mapped_column(String(64), nullable=False)
    scope: Mapped[str] = mapped_column(String(32), default="day", nullable=False)
    scope_key: Mapped[str] = mapped_column(String(64), nullable=False)
    value: Mapped[Optional[float]] = mapped_column(Float)
    units: Mapped[Optional[str]] = mapped_column(String(32))
    formula_version: Mapped[str] = mapped_column(String(16), default="1", nullable=False)
    input_sources: Mapped[Optional[list[Any]]] = mapped_column(JSON)
    detail: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON)
    calculated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class AppSetting(Base, TimestampMixin):
    """User preferences the dashboard can change at runtime."""

    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[Optional[str]] = mapped_column(Text)
