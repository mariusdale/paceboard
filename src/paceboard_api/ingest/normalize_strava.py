"""Strava response handlers.

Mirrors :mod:`normalize_garmin`. Strava has no daily-wellness data, so its
handlers cover the athlete profile, gear and activity-adjacent metrics only;
activities themselves flow through :mod:`paceboard_api.ingest.activities` like
Garmin's do.
"""

from __future__ import annotations

import re
from datetime import date
from typing import Any, Callable, Optional

from sqlalchemy.orm import Session

from ..db.models import Athlete, Gear, HeartRateZoneSet, PerformanceMetric
from ..providers.dto import ProviderResult
from .upsert import upsert

SOURCE = "strava"

Handler = Callable[[Session, ProviderResult, Optional[int]], int]
_HANDLERS: dict[str, Handler] = {}

#: Endpoint paths carry ids; match them by pattern rather than exact string.
_ENDPOINT_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"^/athlete$"), "athlete"),
    (re.compile(r"^/athlete/zones$"), "athlete_zones"),
    (re.compile(r"^/athletes/[^/]+/stats$"), "athlete_stats"),
    (re.compile(r"^/gear/[^/]+$"), "gear"),
)


def handler(name: str) -> Callable[[Handler], Handler]:
    def register(fn: Handler) -> Handler:
        _HANDLERS[name] = fn
        return fn

    return register


def get_handler(name: Optional[str]) -> Optional[Handler]:
    return _HANDLERS.get(name) if name else None


def handler_for_endpoint(endpoint: str) -> Optional[str]:
    for pattern, name in _ENDPOINT_PATTERNS:
        if pattern.match(endpoint):
            return name
    return None


def _num(value: Any) -> Optional[float]:
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


@handler("athlete")
def athlete(session: Session, result: ProviderResult, raw_id: Optional[int]) -> int:
    payload = result.data
    if not isinstance(payload, dict) or payload.get("id") is None:
        return 0
    upsert(
        session, Athlete, {"source": SOURCE, "provider_id": str(payload["id"])},
        {
            "display_name": " ".join(
                p for p in (payload.get("firstname"), payload.get("lastname")) if p
            ).strip() or None,
            "sex": payload.get("sex"),
            "weight_kg": _num(payload.get("weight")),
            "measurement_system": payload.get("measurement_preference"),
        },
        raw_payload_id=raw_id,
    )
    written = 1
    for entry in list(payload.get("bikes") or []) + list(payload.get("shoes") or []):
        if not entry.get("id"):
            continue
        upsert(
            session, Gear, {"source": SOURCE, "provider_id": str(entry["id"])},
            {
                "name": entry.get("name"),
                "gear_type": "bike" if entry in (payload.get("bikes") or []) else "shoes",
                "retired": bool(entry.get("retired")),
                "provider_distance_m": _num(entry.get("distance")),
            },
        )
        written += 1
    return written


@handler("gear")
def gear(session: Session, result: ProviderResult, raw_id: Optional[int]) -> int:
    payload = result.data
    if not isinstance(payload, dict) or payload.get("id") is None:
        return 0
    upsert(
        session, Gear, {"source": SOURCE, "provider_id": str(payload["id"])},
        {
            "name": payload.get("name"),
            "brand": payload.get("brand_name"),
            "model": payload.get("model_name"),
            "gear_type": payload.get("frame_type") and "bike" or "shoes",
            "retired": bool(payload.get("retired")),
            "provider_distance_m": _num(payload.get("distance")),
        },
        raw_payload_id=raw_id,
    )
    return 1


@handler("athlete_zones")
def athlete_zones(session: Session, result: ProviderResult, raw_id: Optional[int]) -> int:
    payload = result.data
    if not isinstance(payload, dict):
        return 0
    hr_zones = (payload.get("heart_rate") or {}).get("zones") or []
    if not hr_zones:
        return 0
    upsert(
        session, HeartRateZoneSet, {"source": SOURCE, "sport": "default"},
        {
            "method": "strava",
            "zone_floors": [z.get("min") for z in hr_zones],
            "max_hr": max((z.get("max") or 0) for z in hr_zones) or None,
        },
    )
    return 1


@handler("athlete_stats")
def athlete_stats(session: Session, result: ProviderResult, raw_id: Optional[int]) -> int:
    payload = result.data
    if not isinstance(payload, dict):
        return 0
    today = date.today()
    written = 0
    for bucket, sport in (
        ("all_run_totals", "run"),
        ("all_ride_totals", "ride"),
        ("all_swim_totals", "swim"),
    ):
        totals = payload.get(bucket)
        if not isinstance(totals, dict):
            continue
        for metric, key, units in (
            ("lifetime_distance", "distance", "m"),
            ("lifetime_duration", "moving_time", "s"),
            ("lifetime_elevation", "elevation_gain", "m"),
            ("lifetime_count", "count", "activities"),
        ):
            value = _num(totals.get(key))
            if value is None:
                continue
            upsert(
                session, PerformanceMetric,
                {"source": SOURCE, "metric": metric, "sport": sport, "day": today},
                {"value": value, "units": units},
                raw_payload_id=raw_id,
            )
            written += 1
    return written
