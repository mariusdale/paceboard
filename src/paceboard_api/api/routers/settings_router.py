"""User preferences and storage statistics."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from sqlalchemy import func, select

from ...db.models import AppSetting, Base
from ..deps import SessionDep, SettingsDep
from ..schemas import SettingsUpdate

router = APIRouter(tags=["settings"])

DEFAULTS: dict[str, Any] = {
    "unit_system": None,          # falls back to the env value
    "timezone": None,
    "backfill_days": None,
    "fast_interval_minutes": None,
    # Maps are opt-in: a GPS trace is the most identifying thing in this
    # database, so it is not drawn until the user asks for it.
    "show_maps": "false",
    # Even then, tiles are off by default — fetching them would send route
    # coordinates to a third-party tile server.
    "map_tiles_enabled": "false",
}


def read_settings(session) -> dict[str, str]:
    stored = {
        row.key: row.value
        for row in session.execute(select(AppSetting)).scalars()
    }
    return {k: stored.get(k, v) for k, v in DEFAULTS.items() if stored.get(k, v) is not None}


@router.get("/settings", response_model=dict, summary="Effective settings")
def get_settings_route(session: SessionDep, settings: SettingsDep) -> dict[str, Any]:
    stored = read_settings(session)
    return {
        "unit_system": stored.get("unit_system", settings.unit_system),
        "timezone": stored.get("timezone", settings.timezone),
        "backfill_days": int(stored.get("backfill_days", settings.backfill_days)),
        "fast_interval_minutes": int(
            stored.get("fast_interval_minutes", settings.fast_interval_minutes)
        ),
        "show_maps": stored.get("show_maps", "false") == "true",
        "map_tiles_enabled": stored.get("map_tiles_enabled", "false") == "true",
        "scheduler_enabled": settings.scheduler_enabled,
        "reconcile_days": settings.reconcile_days,
        "fixture_mode": settings.fixture_mode,
        "storage": storage_stats(session, settings),
        "notes": {
            "map_tiles": "Tile rendering fetches images from a third-party tile "
                         "server, which reveals the area of your routes. Off by "
                         "default; Paceboard draws routes locally instead.",
            "restart_required": ["timezone"],
        },
    }


@router.put("/settings", response_model=dict, summary="Update settings")
def update_settings(
    body: SettingsUpdate, session: SessionDep, settings: SettingsDep
) -> dict[str, Any]:
    for key, value in body.model_dump(exclude_none=True).items():
        stored = session.get(AppSetting, key)
        text = "true" if value is True else "false" if value is False else str(value)
        if stored is None:
            session.add(AppSetting(key=key, value=text))
        else:
            stored.value = text
    session.commit()
    return get_settings_route(session, settings)


def storage_stats(session, settings) -> dict[str, Any]:
    tables = {}
    for table in Base.metadata.sorted_tables:
        try:
            tables[table.name] = session.execute(
                select(func.count()).select_from(table)
            ).scalar_one()
        except Exception:  # pragma: no cover - table may not exist pre-migration
            tables[table.name] = 0
    size = settings.database_path.stat().st_size if settings.database_path.exists() else 0
    return {
        "database_path": str(settings.database_path),
        "database_bytes": size,
        "database_mb": round(size / (1024 * 1024), 2),
        "rows": dict(sorted(tables.items(), key=lambda kv: -kv[1])),
        "total_rows": sum(tables.values()),
    }
