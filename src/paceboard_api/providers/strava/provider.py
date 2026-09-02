"""StravaApiProvider — official REST API adapter behind the provider interface.

Mirrors :class:`~paceboard_api.providers.garmin.provider.GarminMcpProvider`, so
the ingestion pipeline treats the two identically. When Strava credentials are
absent every method returns an ``UNSUPPORTED`` result rather than raising, which
is what lets the Garmin-only dashboard work unchanged.
"""

from __future__ import annotations

from datetime import date, datetime, time as dtime, timedelta, timezone
from typing import Any, Optional

from ...logging_conf import get_logger
from ..dto import (
    ActivitySummaryDTO,
    Capability,
    LapDTO,
    ProviderResult,
    ResultStatus,
    StreamSetDTO,
    ZoneDTO,
)
from .client import StravaClient, StravaNotConnected
from .tokens import TokenStore

log = get_logger("paceboard.strava.provider")

PROVIDER = "strava"

SPORT_MAP: dict[str, str] = {
    "run": "run", "trailrun": "run", "virtualrun": "run",
    "ride": "ride", "virtualride": "ride", "gravelride": "ride",
    "mountainbikeride": "ride", "ebikeride": "ride", "velomobile": "ride",
    "walk": "walk", "hike": "hike", "snowshoe": "ski",
    "swim": "swim", "rowing": "row", "virtualrow": "row",
    "kayaking": "paddle", "canoeing": "paddle", "standuppaddling": "paddle",
    "weighttraining": "strength", "crossfit": "strength",
    "workout": "cardio", "elliptical": "cardio", "stairstepper": "cardio",
    "yoga": "yoga", "alpineski": "ski", "backcountryski": "ski",
    "nordicski": "ski", "rollerski": "ski", "iceskate": "ski",
}

#: Endpoints Paceboard reads, published to the capability catalog so the UI can
#: show Strava coverage next to Garmin's.
STRAVA_CAPABILITIES: tuple[tuple[str, str, str, str, str], ...] = (
    ("/athlete", "account", "account", "daily", "athlete"),
    ("/athlete/zones", "account", "account", "daily", "athlete_zones"),
    ("/athletes/{id}/stats", "account", "account", "daily", "athlete_stats"),
    ("/athlete/activities", "activities", "range", "fast", "activities_list"),
    ("/activities/{id}", "activities", "activity", "per_activity", "activity_detail"),
    ("/activities/{id}/laps", "activities", "activity", "per_activity", "activity_laps"),
    ("/activities/{id}/zones", "activities", "activity", "per_activity", "activity_zones"),
    ("/activities/{id}/streams", "activities", "activity", "per_activity",
     "activity_streams"),
    ("/gear/{id}", "account", "account", "daily", "gear"),
    ("/athletes/{id}/routes", "account", "account", "weekly", "routes"),
)


def canonical_sport(sport_type: Optional[str]) -> str:
    if not sport_type:
        return "other"
    return SPORT_MAP.get(str(sport_type).strip().lower(), "other")


def _parse_dt(value: Any) -> Optional[datetime]:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
    return parsed


def _num(value: Any) -> Optional[float]:
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _unsupported(endpoint: str, reason: str) -> ProviderResult:
    return ProviderResult(
        provider=PROVIDER, endpoint=endpoint, params={},
        status=ResultStatus.UNSUPPORTED, message=reason,
    )


class StravaApiProvider:
    """Read-only Strava adapter over the official v3 REST API."""

    name = PROVIDER

    def __init__(self, client: StravaClient) -> None:
        self.client = client

    @classmethod
    def from_settings(cls, settings) -> "StravaApiProvider":
        store = TokenStore(settings.token_path, settings.secret_key_path)
        return cls(
            StravaClient(
                settings.strava_client_id,
                settings.strava_client_secret,
                settings.strava_redirect_uri,
                store,
            )
        )

    # -- lifecycle -------------------------------------------------------

    @property
    def configured(self) -> bool:
        return self.client.configured

    @property
    def connected(self) -> bool:
        return self.client.connected

    async def connect(self) -> None:
        if not self.configured:
            raise StravaNotConnected(
                "Strava client credentials are not configured (see .env.example)"
            )
        if not self.connected:
            raise StravaNotConnected("Strava has not been authorized yet")

    async def close(self) -> None:
        await self.client.close()

    async def health(self) -> tuple[bool, str]:
        if not self.configured:
            return False, "Strava client credentials not configured"
        tokens = self.client.store.load()
        if tokens is None:
            return False, "Strava not connected — authorize from Settings"
        result = await self.client.athlete()
        if result.ok:
            return True, "Connected"
        return False, result.message or "Strava request failed"

    async def discover_capabilities(self) -> list[Capability]:
        available = self.connected
        return [
            Capability(
                name=name,
                category=category,
                scope=scope,
                cadence=cadence,
                handler=handler,
                enabled=available,
                description=f"Strava REST endpoint {name}",
                status="available" if available else "unavailable",
            )
            for name, category, scope, cadence, handler in STRAVA_CAPABILITIES
        ]

    # -- account ---------------------------------------------------------

    async def fetch_account(self) -> list[ProviderResult]:
        if not self.connected:
            return [_unsupported("/athlete", "Strava not connected")]
        results = [await self.client.athlete(), await self.client.athlete_zones()]
        athlete = results[0]
        if athlete.ok and isinstance(athlete.data, dict):
            athlete_id = str(athlete.data.get("id", ""))
            if athlete_id:
                results.append(await self.client.athlete_stats(athlete_id))
            for gear in list(athlete.data.get("bikes") or []) + list(
                athlete.data.get("shoes") or []
            ):
                gear_id = gear.get("id")
                if gear_id:
                    results.append(await self.client.gear(str(gear_id)))
        return results

    async def fetch_daily(self, day: date, categories: list[str]) -> list[ProviderResult]:
        """Strava exposes no daily-wellness endpoints; nothing to fetch."""
        return []

    async def fetch_range(
        self, start: date, end: date, categories: list[str]
    ) -> list[ProviderResult]:
        return []

    # -- activities ------------------------------------------------------

    async def fetch_activities(
        self, start: date, end: date
    ) -> tuple[list[ActivitySummaryDTO], list[ProviderResult]]:
        if not self.connected:
            return [], [_unsupported("/athlete/activities", "Strava not connected")]
        after = int(
            datetime.combine(start, dtime.min, tzinfo=timezone.utc).timestamp()
        )
        before = int(
            datetime.combine(end + timedelta(days=1), dtime.min, tzinfo=timezone.utc)
            .timestamp()
        )
        summaries: list[ActivitySummaryDTO] = []
        results: list[ProviderResult] = []
        page = 1
        while page <= 100:
            result = await self.client.activities_page(after, before, page)
            results.append(result)
            if not result.ok or not isinstance(result.data, list):
                break
            for item in result.data:
                dto = self._summary(item)
                if dto is not None:
                    summaries.append(dto)
            if len(result.data) < 100:
                break
            page += 1
        return summaries, results

    def _summary(self, item: dict[str, Any]) -> Optional[ActivitySummaryDTO]:
        start = _parse_dt(item.get("start_date"))
        provider_id = item.get("id")
        if start is None or provider_id is None:
            return None
        latlng = item.get("start_latlng") or []
        sport_type = item.get("sport_type") or item.get("type")
        return ActivitySummaryDTO(
            source=PROVIDER,
            provider_id=str(provider_id),
            name=item.get("name"),
            sport=canonical_sport(sport_type),
            provider_type=sport_type,
            start_time_utc=start,
            start_time_local=item.get("start_date_local"),
            utc_offset_seconds=int(item["utc_offset"]) if item.get("utc_offset") else None,
            duration_s=_num(item.get("elapsed_time")),
            moving_duration_s=_num(item.get("moving_time")),
            elapsed_duration_s=_num(item.get("elapsed_time")),
            distance_m=_num(item.get("distance")),
            elevation_gain_m=_num(item.get("total_elevation_gain")),
            avg_speed_mps=_num(item.get("average_speed")),
            max_speed_mps=_num(item.get("max_speed")),
            avg_hr=_num(item.get("average_heartrate")),
            max_hr=_num(item.get("max_heartrate")),
            avg_cadence=_num(item.get("average_cadence")),
            avg_power_w=_num(item.get("average_watts")),
            max_power_w=_num(item.get("max_watts")),
            normalized_power_w=_num(item.get("weighted_average_watts")),
            calories=_num(item.get("calories") or item.get("kilojoules")),
            avg_temperature_c=_num(item.get("average_temp")),
            device_name=item.get("device_name"),
            external_id=item.get("external_id"),
            upload_id=str(item["upload_id"]) if item.get("upload_id") else None,
            start_lat=_num(latlng[0]) if len(latlng) == 2 else None,
            start_lng=_num(latlng[1]) if len(latlng) == 2 else None,
            gear_provider_id=item.get("gear_id"),
            extra={
                k: item.get(k)
                for k in ("trainer", "commute", "manual", "private", "achievement_count",
                          "kudos_count", "pr_count", "suffer_score", "map")
                if item.get(k) is not None
            },
        )

    async def fetch_activity_detail(
        self, provider_id: str
    ) -> tuple[Optional[ActivitySummaryDTO], list[ProviderResult]]:
        if not self.connected:
            return None, [_unsupported(f"/activities/{provider_id}", "Strava not connected")]
        result = await self.client.activity(provider_id)
        if not result.ok or not isinstance(result.data, dict):
            return None, [result]
        return self._summary(result.data), [result]

    async def fetch_activity_laps(
        self, provider_id: str
    ) -> tuple[list[LapDTO], list[ProviderResult]]:
        if not self.connected:
            return [], [_unsupported(f"/activities/{provider_id}/laps", "Strava not connected")]
        result = await self.client.activity_laps(provider_id)
        laps: list[LapDTO] = []
        if result.ok and isinstance(result.data, list):
            for index, lap in enumerate(result.data, start=1):
                laps.append(
                    LapDTO(
                        lap_index=int(lap.get("lap_index") or index),
                        start_time_utc=_parse_dt(lap.get("start_date")),
                        duration_s=_num(lap.get("elapsed_time")),
                        moving_duration_s=_num(lap.get("moving_time")),
                        distance_m=_num(lap.get("distance")),
                        avg_speed_mps=_num(lap.get("average_speed")),
                        max_speed_mps=_num(lap.get("max_speed")),
                        avg_hr=_num(lap.get("average_heartrate")),
                        max_hr=_num(lap.get("max_heartrate")),
                        avg_power_w=_num(lap.get("average_watts")),
                        avg_cadence=_num(lap.get("average_cadence")),
                        elevation_gain_m=_num(lap.get("total_elevation_gain")),
                    )
                )
        return laps, [result]

    async def fetch_activity_zones(
        self, provider_id: str
    ) -> tuple[list[ZoneDTO], list[ProviderResult]]:
        if not self.connected:
            return [], [_unsupported(f"/activities/{provider_id}/zones", "Strava not connected")]
        result = await self.client.activity_zones(provider_id)
        zones: list[ZoneDTO] = []
        if result.ok and isinstance(result.data, list):
            for bucket in result.data:
                kind = "hr" if bucket.get("type") == "heartrate" else bucket.get("type", "hr")
                for index, entry in enumerate(bucket.get("distribution_buckets") or [], 1):
                    zones.append(
                        ZoneDTO(
                            zone_kind=str(kind),
                            zone_number=index,
                            seconds_in_zone=_num(entry.get("time")),
                            low_boundary=_num(entry.get("min")),
                            high_boundary=_num(entry.get("max")),
                        )
                    )
        return zones, [result]

    async def fetch_activity_streams(
        self, provider_id: str
    ) -> tuple[Optional[StreamSetDTO], list[ProviderResult]]:
        if not self.connected:
            return None, [
                _unsupported(f"/activities/{provider_id}/streams", "Strava not connected")
            ]
        result = await self.client.activity_streams(provider_id)
        if not result.ok or not isinstance(result.data, dict):
            return None, [result]
        channels: dict[str, list[Optional[float]]] = {}
        units: dict[str, str] = {}
        for key, payload in result.data.items():
            data = payload.get("data") if isinstance(payload, dict) else None
            if not isinstance(data, list):
                continue
            if key == "latlng":
                channels["lat"] = [p[0] if isinstance(p, list) and p else None for p in data]
                channels["lng"] = [p[1] if isinstance(p, list) and len(p) > 1 else None
                                   for p in data]
                units["lat"] = units["lng"] = "deg"
                continue
            channels[key] = [
                float(v) if isinstance(v, (int, float)) else
                (1.0 if v is True else 0.0 if v is False else None)
                for v in data
            ]
            units[key] = payload.get("series_type", "") if isinstance(payload, dict) else ""
        if not channels:
            return None, [result]
        return StreamSetDTO(channels=channels, units=units), [result]
