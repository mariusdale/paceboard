"""Gear and device inventory."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from sqlalchemy import select

from ...analytics import service as analytics
from ...db.models import Athlete, Device, HeartRateZoneSet
from ..deps import SessionDep
from ..schemas import GearResponse

router = APIRouter(tags=["gear"])


@router.get("/gear", response_model=list[GearResponse], summary="Gear with mileage")
def list_gear(session: SessionDep) -> list[GearResponse]:
    return [GearResponse.model_validate(item) for item in analytics.gear_mileage(session)]


@router.get("/devices", response_model=list[dict], summary="Devices")
def list_devices(session: SessionDep) -> list[dict[str, Any]]:
    rows = session.execute(select(Device).order_by(Device.is_primary.desc())).scalars()
    # Serial numbers are stored for device matching but never returned.
    return [
        {
            "id": row.id, "source": row.source, "provider_id": row.provider_id,
            "name": row.name, "model": row.model, "is_primary": row.is_primary,
            "last_used_at": row.last_used_at.isoformat() if row.last_used_at else None,
            "details": row.details,
        }
        for row in rows
    ]


@router.get("/profile", response_model=dict, summary="Athlete profile and zones")
def profile(session: SessionDep) -> dict[str, Any]:
    athletes = session.execute(select(Athlete)).scalars().all()
    zones = session.execute(select(HeartRateZoneSet)).scalars().all()
    return {
        "athletes": [
            {
                "source": a.source,
                "display_name": a.display_name,
                "sex": a.sex,
                "birth_date": a.birth_date.isoformat() if a.birth_date else None,
                "height_cm": a.height_cm,
                "weight_kg": a.weight_kg,
                "measurement_system": a.measurement_system,
                "vo2max_running": a.vo2max_running,
                "vo2max_cycling": a.vo2max_cycling,
                "lactate_threshold_hr": a.lactate_threshold_hr,
                "lactate_threshold_speed_mps": a.lactate_threshold_speed_mps,
            }
            for a in athletes
        ],
        "heart_rate_zones": [
            {
                "source": z.source, "sport": z.sport, "method": z.method,
                "resting_hr": z.resting_hr, "max_hr": z.max_hr,
                "lactate_threshold_hr": z.lactate_threshold_hr,
                "zone_floors": z.zone_floors,
            }
            for z in zones
        ],
    }
