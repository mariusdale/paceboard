"""Typed internal DTOs returned by every provider adapter.

Adapters translate provider-shaped responses into these; the original response
travels alongside as :class:`ProviderResult.raw` so nothing is lost and the raw
payload store keeps a verbatim copy.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from enum import Enum
from typing import Any, Optional


class ResultStatus(str, Enum):
    """Outcome of a single provider call.

    The distinction matters: ``NO_DATA`` and ``UNSUPPORTED`` are normal
    (a metric the watch does not record), whereas ``ERROR`` and
    ``RATE_LIMITED`` are worth surfacing and, for the latter, retrying.
    """

    OK = "ok"
    NO_DATA = "no_data"
    UNSUPPORTED = "unsupported"
    INVALID_REQUEST = "invalid_request"
    ERROR = "error"
    RATE_LIMITED = "rate_limited"
    TIMEOUT = "timeout"
    PROTOCOL_ERROR = "protocol_error"

    @property
    def is_success(self) -> bool:
        return self is ResultStatus.OK

    @property
    def is_retryable(self) -> bool:
        return self in {
            ResultStatus.RATE_LIMITED,
            ResultStatus.TIMEOUT,
            ResultStatus.PROTOCOL_ERROR,
        }

    @property
    def is_permanent(self) -> bool:
        return self in {
            ResultStatus.NO_DATA,
            ResultStatus.UNSUPPORTED,
            ResultStatus.INVALID_REQUEST,
        }


@dataclass(slots=True)
class ProviderResult:
    """A single provider call: what was asked, what came back, how long it took."""

    provider: str
    endpoint: str
    params: dict[str, Any]
    status: ResultStatus
    data: Any = None
    text: Optional[str] = None
    message: Optional[str] = None
    duration_ms: int = 0
    retrieved_at: datetime = field(default_factory=lambda: datetime.utcnow())

    @property
    def ok(self) -> bool:
        return self.status.is_success

    @property
    def content_type(self) -> str:
        return "json" if self.data is not None else "text"


@dataclass(slots=True)
class Capability:
    """One callable provider operation plus how Paceboard intends to use it."""

    name: str
    category: str
    scope: str  # daily | range | activity | account
    cadence: str  # fast | daily | weekly | on_demand | per_activity
    handler: Optional[str] = None
    enabled: bool = True
    description: str = ""
    expected_arguments: dict[str, Any] = field(default_factory=dict)
    status: str = "unknown"
    input_schema: Optional[dict[str, Any]] = None


@dataclass(slots=True)
class ActivitySummaryDTO:
    """Provider-neutral activity summary used by the normalizer."""

    source: str
    provider_id: str
    name: Optional[str]
    sport: str
    provider_type: Optional[str]
    start_time_utc: datetime
    start_time_local: Optional[str] = None
    utc_offset_seconds: Optional[int] = None
    duration_s: Optional[float] = None
    moving_duration_s: Optional[float] = None
    elapsed_duration_s: Optional[float] = None
    distance_m: Optional[float] = None
    elevation_gain_m: Optional[float] = None
    elevation_loss_m: Optional[float] = None
    avg_speed_mps: Optional[float] = None
    max_speed_mps: Optional[float] = None
    avg_hr: Optional[float] = None
    max_hr: Optional[float] = None
    avg_cadence: Optional[float] = None
    avg_power_w: Optional[float] = None
    max_power_w: Optional[float] = None
    normalized_power_w: Optional[float] = None
    calories: Optional[float] = None
    training_load: Optional[float] = None
    aerobic_training_effect: Optional[float] = None
    anaerobic_training_effect: Optional[float] = None
    training_effect_label: Optional[str] = None
    perceived_effort: Optional[float] = None
    avg_temperature_c: Optional[float] = None
    device_name: Optional[str] = None
    external_id: Optional[str] = None
    upload_id: Optional[str] = None
    start_lat: Optional[float] = None
    start_lng: Optional[float] = None
    gear_provider_id: Optional[str] = None
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class LapDTO:
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
    elevation_loss_m: Optional[float] = None
    calories: Optional[float] = None
    intensity_type: Optional[str] = None


@dataclass(slots=True)
class ZoneDTO:
    zone_kind: str
    zone_number: int
    seconds_in_zone: Optional[float] = None
    low_boundary: Optional[float] = None
    high_boundary: Optional[float] = None


@dataclass(slots=True)
class StreamSetDTO:
    """Aligned per-sample channels. Every present channel has equal length."""

    channels: dict[str, list[Optional[float]]] = field(default_factory=dict)
    units: dict[str, str] = field(default_factory=dict)

    @property
    def point_count(self) -> int:
        for values in self.channels.values():
            return len(values)
        return 0


@dataclass(slots=True)
class DailyHealthDTO:
    day: date
    values: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class SyncTaskOutcome:
    """Result of one unit of sync work, aggregated into the run summary."""

    capability: str
    status: ResultStatus
    records: int = 0
    message: Optional[str] = None
