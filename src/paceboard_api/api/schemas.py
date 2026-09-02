"""Pydantic response/request models.

Serialization rules that apply everywhere:

* timestamps go out as ISO-8601 UTC (``*_utc``) with the provider's local string
  preserved alongside;
* every record carries its ``source``;
* nothing token-shaped is ever a field on a response model.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

SourceName = Literal["garmin", "strava"]


class ApiModel(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class Page(ApiModel):
    total: int
    limit: int
    offset: int
    has_more: bool


class ErrorBody(ApiModel):
    code: str
    message: str
    detail: Optional[dict[str, Any]] = None


class StatusResponse(ApiModel):
    app: str = "paceboard"
    version: str
    timezone: str
    unit_system: str
    fixture_mode: bool
    database_path: str
    database_bytes: int
    bound_host: str
    api_port: int
    counts: dict[str, int]
    last_sync: Optional[dict[str, Any]] = None
    freshness: list[dict[str, Any]] = Field(default_factory=list)


class ConnectionResponse(ApiModel):
    provider: str
    status: str
    display_name: Optional[str] = None
    endpoint: Optional[str] = None
    configured: bool = True
    last_checked_at: Optional[datetime] = None
    last_success_at: Optional[datetime] = None
    last_error: Optional[str] = None
    details: Optional[dict[str, Any]] = None


class CapabilityResponse(ApiModel):
    provider: str
    name: str
    category: str
    scope: str
    cadence: str
    enabled: bool
    status: str
    handler: Optional[str] = None
    description: Optional[str] = None
    expected_arguments: Optional[dict[str, Any]] = None
    last_called_at: Optional[datetime] = None
    last_status: Optional[str] = None
    last_note: Optional[str] = None
    call_count: int = 0
    error_count: int = 0


class SyncRequestBody(ApiModel):
    providers: list[SourceName] = Field(default_factory=lambda: ["garmin", "strava"])
    mode: Literal["incremental", "backfill", "today"] = "incremental"
    categories: list[Literal["account", "activities", "daily_health", "training"]] = (
        Field(default_factory=lambda: ["account", "activities", "daily_health", "training"])
    )
    start: Optional[date] = None
    end: Optional[date] = None
    enrich: bool = True


class SyncRunResponse(ApiModel):
    id: int
    providers: str
    mode: str
    categories: Optional[str] = None
    status: str
    trigger: str
    started_at: datetime
    finished_at: Optional[datetime] = None
    range_start: Optional[date] = None
    range_end: Optional[date] = None
    records_written: int
    errors_count: int
    current_step: Optional[str] = None
    cancel_requested: bool = False
    summary: Optional[dict[str, Any]] = None
    errors: list[dict[str, Any]] = Field(default_factory=list)


class ActivitySourceResponse(ApiModel):
    source: str
    provider_id: str
    name: Optional[str] = None
    sport: str
    provider_type: Optional[str] = None
    start_time_utc: datetime
    duration_s: Optional[float] = None
    distance_m: Optional[float] = None
    detail_status: str


class ActivityResponse(ApiModel):
    id: int
    canonical_key: str
    primary_source: str
    name: Optional[str] = None
    sport: str
    provider_type: Optional[str] = None
    start_time_utc: datetime
    start_time_local: Optional[str] = None
    utc_offset_seconds: Optional[int] = None
    local_date: Optional[date] = None
    duration_s: Optional[float] = None
    moving_duration_s: Optional[float] = None
    distance_m: Optional[float] = None
    elevation_gain_m: Optional[float] = None
    elevation_loss_m: Optional[float] = None
    avg_speed_mps: Optional[float] = None
    max_speed_mps: Optional[float] = None
    avg_hr: Optional[float] = None
    max_hr: Optional[float] = None
    avg_cadence: Optional[float] = None
    avg_power_w: Optional[float] = None
    normalized_power_w: Optional[float] = None
    calories: Optional[float] = None
    training_load: Optional[float] = None
    aerobic_training_effect: Optional[float] = None
    anaerobic_training_effect: Optional[float] = None
    training_effect_label: Optional[str] = None
    avg_temperature_c: Optional[float] = None
    device_name: Optional[str] = None
    has_gps: bool = False
    has_streams: bool = False
    detail_status: str = "pending"
    stream_status: str = "pending"
    duplicate_state: str = "single"
    field_provenance: Optional[dict[str, Any]] = None
    sources: list[ActivitySourceResponse] = Field(default_factory=list)


class ActivityListResponse(ApiModel):
    items: list[ActivityResponse]
    page: Page


class LapResponse(ApiModel):
    source: str
    lap_index: int
    start_time_utc: Optional[datetime] = None
    duration_s: Optional[float] = None
    moving_duration_s: Optional[float] = None
    distance_m: Optional[float] = None
    avg_speed_mps: Optional[float] = None
    max_speed_mps: Optional[float] = None
    avg_hr: Optional[float] = None
    max_hr: Optional[float] = None
    avg_power_w: Optional[float] = None
    avg_cadence: Optional[float] = None
    elevation_gain_m: Optional[float] = None
    calories: Optional[float] = None
    intensity_type: Optional[str] = None


class GearResponse(ApiModel):
    id: int
    source: str
    provider_id: str
    name: Optional[str] = None
    brand: Optional[str] = None
    model: Optional[str] = None
    gear_type: Optional[str] = None
    retired: bool = False
    provider_distance_m: Optional[float] = None
    observed_distance_m: float = 0.0
    observed_activity_count: int = 0


class RawPayloadResponse(ApiModel):
    id: int
    provider: str
    endpoint: str
    params: Optional[dict[str, Any]] = None
    schema_version: str
    status: str
    content_type: str
    byte_size: int
    duration_ms: Optional[int] = None
    retrieved_at: datetime
    reference_kind: Optional[str] = None
    reference_id: Optional[str] = None


class RawPayloadDetail(RawPayloadResponse):
    content: Any = None


class ToolCallRequest(ApiModel):
    """Manual read-tool invocation from the Data Explorer.

    Only tool names on the Garmin read-only allowlist are accepted, and the
    arguments are validated against the catalog's expected argument names before
    anything is sent to the MCP server.
    """

    tool: str = Field(min_length=1, max_length=128)
    arguments: dict[str, Any] = Field(default_factory=dict)


class SettingsUpdate(ApiModel):
    unit_system: Optional[Literal["metric", "imperial"]] = None
    timezone: Optional[str] = Field(default=None, max_length=64)
    backfill_days: Optional[int] = Field(default=None, ge=1, le=3650)
    fast_interval_minutes: Optional[int] = Field(default=None, ge=5, le=1440)
    show_maps: Optional[bool] = None
    map_tiles_enabled: Optional[bool] = None
