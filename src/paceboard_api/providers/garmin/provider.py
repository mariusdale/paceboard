"""GarminMcpProvider — the only path Garmin data takes into Paceboard.

The provider owns request shaping (date windows, provider range caps, paging)
and turns tool responses into DTOs. It never touches python-garminconnect: the
MCP server is the provider boundary, exactly as the deployment constraints
require.
"""

from __future__ import annotations

import asyncio
from datetime import date, datetime, timedelta, timezone
from typing import Any, Iterable, Optional

from ...logging_conf import get_logger
from ..base import ProviderUnavailable
from ..dto import (
    ActivitySummaryDTO,
    Capability,
    LapDTO,
    ProviderResult,
    StreamSetDTO,
    ZoneDTO,
)
from . import catalog
from .mcp_client import GarminMcpClient, GarminMcpUnavailable

log = get_logger("paceboard.garmin.provider")

PROVIDER = "garmin"

#: FIT ``record`` fields Paceboard keeps, mapped to Paceboard stream channels.
FIT_FIELD_CHANNELS: dict[str, str] = {
    "timestamp": "time",
    "distance": "distance",
    "position_lat": "lat_semicircles",
    "position_long": "lng_semicircles",
    "altitude": "altitude",
    "enhanced_altitude": "altitude",
    "speed": "velocity_smooth",
    "enhanced_speed": "velocity_smooth",
    "heart_rate": "heartrate",
    "cadence": "cadence",
    "power": "watts",
    "temperature": "temp",
    "grade": "grade_smooth",
}

STREAM_UNITS = {
    "time": "s",
    "distance": "m",
    "latlng": "deg",
    "altitude": "m",
    "velocity_smooth": "m/s",
    "heartrate": "bpm",
    "cadence": "rpm",
    "watts": "W",
    "temp": "C",
    "grade_smooth": "%",
    "moving": "bool",
}

_SEMICIRCLE_TO_DEGREES = 180.0 / (2**31)

#: Records requested per FIT page. The MCP server re-downloads and re-parses the
#: whole FIT file for every page, so paging is far more expensive than a large
#: single request: measured against a real 2143-record activity, one 5000-record
#: call took 1.2 s where three 1000-record calls took ~3.1 s. Most activities now
#: fit in a single request; longer ones still page correctly.
_FIT_PAGE_SIZE = 5000

#: Hard ceiling on samples kept per activity, so an ultra-distance file cannot
#: pull an unbounded amount of memory or storage.
_MAX_STREAM_POINTS = 20000

#: Garmin's own type keys collapsed onto Paceboard's canonical sports so
#: cross-provider matching and per-sport aggregation compare like with like.
SPORT_MAP: dict[str, str] = {
    "running": "run", "trail_running": "run", "treadmill_running": "run",
    "indoor_running": "run", "track_running": "run", "virtual_run": "run",
    "obstacle_run": "run", "ultra_run": "run", "street_running": "run",
    "cycling": "ride", "road_biking": "ride", "mountain_biking": "ride",
    "gravel_cycling": "ride", "indoor_cycling": "ride", "virtual_ride": "ride",
    "cyclocross": "ride", "downhill_biking": "ride", "e_bike_fitness": "ride",
    "recumbent_cycling": "ride", "track_cycling": "ride", "bmx": "ride",
    "walking": "walk", "casual_walking": "walk", "speed_walking": "walk",
    "hiking": "hike", "mountaineering": "hike",
    "lap_swimming": "swim", "open_water_swimming": "swim", "swimming": "swim",
    "strength_training": "strength", "indoor_cardio": "cardio",
    "cardio": "cardio", "hiit": "cardio", "elliptical": "cardio",
    "indoor_rowing": "row", "rowing": "row", "kayaking": "paddle",
    "stand_up_paddleboarding": "paddle", "yoga": "yoga", "pilates": "yoga",
    "breathwork": "yoga", "meditation": "yoga",
    "resort_skiing_snowboarding": "ski", "backcountry_skiing": "ski",
    "cross_country_skiing": "ski", "skate_skiing": "ski",
    "classic_skiing": "ski", "snowshoeing": "ski",
    "multi_sport": "multisport", "transition": "transition",
}


def canonical_sport(provider_type: Optional[str]) -> str:
    if not provider_type:
        return "other"
    key = str(provider_type).strip().lower().replace(" ", "_")
    if key in SPORT_MAP:
        return SPORT_MAP[key]
    for token, sport in (("run", "run"), ("cycl", "ride"), ("bik", "ride"),
                         ("swim", "swim"), ("walk", "walk"), ("hik", "hike"),
                         ("row", "row"), ("ski", "ski"), ("strength", "strength")):
        if token in key:
            return sport
    return "other"


def _parse_dt(value: Any) -> Optional[datetime]:
    """Parse Garmin's several timestamp shapes into a naive UTC datetime."""
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)):
        # Epoch milliseconds (sleep_start/sleep_end) vs seconds.
        seconds = value / 1000.0 if value > 1e11 else float(value)
        return datetime.fromtimestamp(seconds, tz=timezone.utc).replace(tzinfo=None)
    text = str(value).strip().replace("Z", "+00:00")
    text = text.replace(".0 ", " ").replace(" ", "T", 1) if " " in text else text
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        for fmt in ("%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
            try:
                parsed = datetime.strptime(text[: len(fmt) + 6], fmt)
                break
            except ValueError:
                continue
        else:
            return None
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
    return parsed


def _num(value: Any) -> Optional[float]:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value))
    except (TypeError, ValueError):
        return None


class GarminMcpProvider:
    """Read-only Garmin adapter over the MCP streamable-HTTP transport."""

    name = PROVIDER

    def __init__(self, client: GarminMcpClient) -> None:
        self.client = client
        self._capabilities: list[Capability] = []

    @classmethod
    def from_settings(cls, settings) -> "GarminMcpProvider":
        return cls(
            GarminMcpClient(
                settings.garmin_mcp_url,
                timeout=settings.garmin_mcp_timeout,
                concurrency=settings.garmin_mcp_concurrency,
                max_retries=settings.garmin_mcp_max_retries,
            )
        )

    # -- lifecycle --------------------------------------------------------

    async def connect(self) -> None:
        try:
            await self.client.connect()
        except GarminMcpUnavailable as exc:
            raise ProviderUnavailable(PROVIDER, str(exc)) from exc

    async def close(self) -> None:
        await self.client.close()

    async def health(self) -> tuple[bool, str]:
        return await self.client.ping()

    async def discover_capabilities(self) -> list[Capability]:
        await self.connect()
        self._capabilities = self.client.capabilities()
        return self._capabilities

    def _available(self, tool: str) -> bool:
        names = self.client.server_tool_names
        return not names or tool in names

    # -- generic calling --------------------------------------------------

    async def call_tool(self, tool: str, arguments: dict[str, Any]) -> ProviderResult:
        """Explicit single-tool invocation (Data Explorer / smoke tests)."""
        return await self.client.call(tool, arguments)

    def _args_for(self, spec: catalog.ToolSpec, **window: Any) -> dict[str, Any]:
        args: dict[str, Any] = dict(spec.extra_args)
        for key in spec.args:
            if key in window and window[key] is not None:
                args[key] = window[key]
        return args

    async def _run_specs(
        self, specs: Iterable[catalog.ToolSpec], **window: Any
    ) -> list[ProviderResult]:
        tasks = []
        for spec in specs:
            if not self._available(spec.name):
                continue
            tasks.append(self.client.call(spec.name, self._args_for(spec, **window)))
        if not tasks:
            return []
        return list(await asyncio.gather(*tasks))

    # -- category fetches -------------------------------------------------

    async def fetch_daily(self, day: date, categories: list[str]) -> list[ProviderResult]:
        specs = [
            s
            for s in catalog.SCHEDULED_TOOLS
            if s.scope == "daily" and s.category in categories
        ]
        return await self._run_specs(specs, date=day.isoformat())

    async def fetch_range(
        self, start: date, end: date, categories: list[str]
    ) -> list[ProviderResult]:
        """Range tools, split into provider-legal windows where a cap exists."""
        results: list[ProviderResult] = []
        for spec in catalog.SCHEDULED_TOOLS:
            if spec.scope != "range" or spec.category not in categories:
                continue
            if spec.name == "get_activities_by_date":
                continue  # handled by fetch_activities (needs paging)
            if not self._available(spec.name):
                continue
            for chunk_start, chunk_end in _chunk_range(start, end, spec.max_range_days):
                args = self._args_for(
                    spec,
                    start_date=chunk_start.isoformat(),
                    end_date=chunk_end.isoformat(),
                    date=chunk_end.isoformat(),
                )
                results.append(await self.client.call(spec.name, args))
        return results

    async def fetch_account(self) -> list[ProviderResult]:
        specs = [s for s in catalog.SCHEDULED_TOOLS if s.scope == "account"]
        return await self._run_specs(specs)

    # -- activities -------------------------------------------------------

    async def fetch_activities(
        self, start: date, end: date
    ) -> tuple[list[ActivitySummaryDTO], list[ProviderResult]]:
        summaries: list[ActivitySummaryDTO] = []
        results: list[ProviderResult] = []
        page = 0
        while True:
            result = await self.client.call(
                "get_activities_by_date",
                {
                    "start_date": start.isoformat(),
                    "end_date": end.isoformat(),
                    "page": page,
                    "page_size": 100,
                },
            )
            results.append(result)
            if not result.ok or not isinstance(result.data, dict):
                break
            for item in result.data.get("activities") or []:
                dto = self._summary_from_list_item(item)
                if dto is not None:
                    summaries.append(dto)
            if not result.data.get("has_more"):
                break
            page += 1
            if page > 100:  # hard stop; 10k activities in one window is a bug
                log.warning("Stopping Garmin activity paging at page 100")
                break
        return summaries, results

    def _summary_from_list_item(self, item: dict[str, Any]) -> Optional[ActivitySummaryDTO]:
        provider_id = item.get("id")
        start = _parse_dt(item.get("start_time_gmt") or item.get("start_time"))
        if provider_id is None or start is None:
            return None
        provider_type = item.get("type")
        return ActivitySummaryDTO(
            source=PROVIDER,
            provider_id=str(provider_id),
            name=item.get("name"),
            sport=canonical_sport(provider_type),
            provider_type=provider_type,
            start_time_utc=start,
            duration_s=_num(item.get("duration_seconds")),
            distance_m=_num(item.get("distance_meters")),
            elevation_gain_m=_num(item.get("elevation_gain_meters")),
            elevation_loss_m=_num(item.get("elevation_loss_meters")),
            avg_hr=_num(item.get("avg_hr_bpm")),
            max_hr=_num(item.get("max_hr_bpm")),
            calories=_num(item.get("calories")),
            extra={"event_type": item.get("event_type")},
        )

    async def fetch_activity_detail(
        self, provider_id: str
    ) -> tuple[Optional[ActivitySummaryDTO], list[ProviderResult]]:
        result = await self.client.call("get_activity", {"activity_id": provider_id})
        results = [result]
        if not result.ok or not isinstance(result.data, dict):
            return None, results
        item = result.data
        start_gmt = _parse_dt(item.get("start_time_gmt"))
        start_local_raw = item.get("start_time_local")
        start_local = _parse_dt(start_local_raw)
        offset = None
        if start_gmt and start_local:
            offset = int((start_local - start_gmt).total_seconds())
        provider_type = item.get("type")
        dto = ActivitySummaryDTO(
            source=PROVIDER,
            provider_id=str(item.get("id") or provider_id),
            name=item.get("name"),
            sport=canonical_sport(provider_type),
            provider_type=provider_type,
            start_time_utc=start_gmt or datetime.utcnow(),
            start_time_local=str(start_local_raw) if start_local_raw else None,
            utc_offset_seconds=offset,
            duration_s=_num(item.get("duration_seconds")),
            moving_duration_s=_num(item.get("moving_duration_seconds")),
            elapsed_duration_s=_num(item.get("elapsed_duration_seconds")),
            distance_m=_num(item.get("distance_meters")),
            elevation_gain_m=_num(item.get("elevation_gain_meters")),
            elevation_loss_m=_num(item.get("elevation_loss_meters")),
            avg_speed_mps=_num(item.get("avg_speed_mps")),
            max_speed_mps=_num(item.get("max_speed_mps")),
            avg_hr=_num(item.get("avg_hr_bpm")),
            max_hr=_num(item.get("max_hr_bpm")),
            avg_cadence=_num(item.get("avg_cadence") or item.get("avg_running_cadence")),
            avg_power_w=_num(item.get("avg_power_w") or item.get("avg_power")),
            max_power_w=_num(item.get("max_power_w") or item.get("max_power")),
            normalized_power_w=_num(item.get("normalized_power")),
            calories=_num(item.get("calories")),
            training_load=_num(item.get("training_load")),
            aerobic_training_effect=_num(item.get("training_effect")),
            anaerobic_training_effect=_num(item.get("anaerobic_training_effect")),
            training_effect_label=item.get("training_effect_label"),
            perceived_effort=_num(item.get("workout_rpe")),
            device_name=item.get("device_manufacturer"),
            extra={
                k: item.get(k)
                for k in (
                    "event_type", "lap_count", "has_splits", "body_battery_impact",
                    "moderate_intensity_minutes", "vigorous_intensity_minutes",
                    "workout_feel", "min_hr_bpm", "max_elevation_meters",
                    "min_elevation_meters", "bmr_calories",
                )
                if item.get(k) is not None
            },
        )
        return dto, results

    async def fetch_activity_laps(
        self, provider_id: str
    ) -> tuple[list[LapDTO], list[ProviderResult]]:
        result = await self.client.call("get_activity_splits", {"activity_id": provider_id})
        laps: list[LapDTO] = []
        if result.ok and isinstance(result.data, dict):
            for lap in result.data.get("laps") or []:
                laps.append(
                    LapDTO(
                        lap_index=int(lap.get("lap_number") or len(laps) + 1),
                        start_time_utc=_parse_dt(lap.get("start_time")),
                        duration_s=_num(lap.get("duration_seconds")),
                        moving_duration_s=_num(lap.get("moving_duration_seconds")),
                        distance_m=_num(lap.get("distance_meters")),
                        avg_speed_mps=_num(lap.get("avg_speed_mps")),
                        max_speed_mps=_num(lap.get("max_speed_mps")),
                        avg_hr=_num(lap.get("avg_hr_bpm")),
                        max_hr=_num(lap.get("max_hr_bpm")),
                        avg_power_w=_num(lap.get("avg_power_w")),
                        avg_cadence=_num(lap.get("avg_cadence")),
                        elevation_gain_m=_num(lap.get("elevation_gain_meters")),
                        elevation_loss_m=_num(lap.get("elevation_loss_meters")),
                        calories=_num(lap.get("calories")),
                        intensity_type=lap.get("intensity_type"),
                    )
                )
        return laps, [result]

    async def fetch_activity_zones(
        self, provider_id: str
    ) -> tuple[list[ZoneDTO], list[ProviderResult]]:
        hr_result, power_result = await asyncio.gather(
            self.client.call("get_activity_hr_in_timezones", {"activity_id": provider_id}),
            self.client.call(
                "get_activity_power_in_timezones", {"activity_id": provider_id}
            ),
        )
        zones: list[ZoneDTO] = []
        for kind, result in (("hr", hr_result), ("power", power_result)):
            if not result.ok or not isinstance(result.data, list):
                continue
            for entry in result.data:
                if not isinstance(entry, dict):
                    continue
                zones.append(
                    ZoneDTO(
                        zone_kind=kind,
                        zone_number=int(entry.get("zoneNumber") or 0),
                        seconds_in_zone=_num(entry.get("secsInZone")),
                        low_boundary=_num(entry.get("zoneLowBoundary")),
                    )
                )
        return zones, [hr_result, power_result]

    async def fetch_activity_streams(
        self, provider_id: str
    ) -> tuple[Optional[StreamSetDTO], list[ProviderResult]]:
        """Assemble per-sample channels from paged FIT ``record`` messages."""
        results: list[ProviderResult] = []
        raw_rows: list[dict[str, Any]] = []
        offset = 0
        while True:
            result = await self.client.call(
                "get_activity_fit_messages",
                {
                    "activity_id": provider_id,
                    "message_types": ["record"],
                    "include_records": True,
                    "message_offset": offset,
                    "message_limit": _FIT_PAGE_SIZE,
                },
            )
            results.append(result)
            if not result.ok or not isinstance(result.data, dict):
                break
            messages = result.data.get("messages") or []
            for message in messages:
                row = _fit_message_to_row(message)
                if row:
                    raw_rows.append(row)
            pagination = result.data.get("pagination") or {}
            next_offset = pagination.get("next_offset")
            total = pagination.get("total_eligible_count") or 0
            if not messages or next_offset is None or next_offset >= total:
                break
            if len(raw_rows) >= _MAX_STREAM_POINTS:
                log.info(
                    "Truncating Garmin stream", extra={"activity_id": provider_id,
                                                       "points": len(raw_rows)}
                )
                break
            offset = int(next_offset)
        if not raw_rows:
            return None, results
        return _rows_to_streams(raw_rows), results


def _fit_message_to_row(message: dict[str, Any]) -> dict[str, Any]:
    row: dict[str, Any] = {}
    for field in message.get("fields") or []:
        name = field.get("name")
        channel = FIT_FIELD_CHANNELS.get(name)
        if channel is None:
            continue
        value = field.get("value")
        if channel == "time":
            row["time"] = _parse_dt(value)
        elif channel in {"lat_semicircles", "lng_semicircles"}:
            raw = field.get("raw_value")
            row[channel] = None if raw is None else float(raw) * _SEMICIRCLE_TO_DEGREES
        else:
            # ``enhanced_*`` variants are more precise; do not let the plain
            # field overwrite a value the enhanced one already provided.
            existing = row.get(channel)
            numeric = _num(value)
            if existing is None or (name.startswith("enhanced_") and numeric is not None):
                row[channel] = numeric
    return row


def _rows_to_streams(rows: list[dict[str, Any]]) -> StreamSetDTO:
    base_time = next((r["time"] for r in rows if r.get("time")), None)
    channels: dict[str, list[Optional[float]]] = {}
    lat = [r.get("lat_semicircles") for r in rows]
    lng = [r.get("lng_semicircles") for r in rows]
    for name in ("time", "distance", "altitude", "velocity_smooth", "heartrate",
                 "cadence", "watts", "temp", "grade_smooth"):
        if name == "time":
            values = [
                (r["time"] - base_time).total_seconds() if r.get("time") and base_time else None
                for r in rows
            ]
        else:
            values = [r.get(name) for r in rows]
        if any(v is not None for v in values):
            channels[name] = values
    if any(v is not None for v in lat) and any(v is not None for v in lng):
        channels["lat"] = lat
        channels["lng"] = lng
    # Derive a moving mask where speed exists; Garmin's FIT has no moving flag.
    speed = channels.get("velocity_smooth")
    if speed:
        channels["moving"] = [None if v is None else float(v > 0.3) for v in speed]
    units = {name: STREAM_UNITS.get(name, "") for name in channels}
    units["lat"] = units["lng"] = "deg"
    return StreamSetDTO(channels=channels, units=units)


def _chunk_range(
    start: date, end: date, max_days: Optional[int]
) -> list[tuple[date, date]]:
    """Split ``[start, end]`` into windows the provider will actually accept."""
    if max_days is None or max_days <= 0:
        return [(start, end)]
    chunks: list[tuple[date, date]] = []
    cursor = start
    while cursor <= end:
        chunk_end = min(cursor + timedelta(days=max_days - 1), end)
        chunks.append((cursor, chunk_end))
        cursor = chunk_end + timedelta(days=1)
    return chunks
