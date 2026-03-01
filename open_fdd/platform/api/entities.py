"""Suggested HA entity mappings from Brick types (e.g. Occupancy_Status -> binary_sensor)."""

from fastapi import APIRouter
from pydantic import BaseModel, Field

from open_fdd.platform.database import get_conn

router = APIRouter(prefix="/entities", tags=["entities"])


class SuggestedEntity(BaseModel):
    """Suggested HA entity for a point (e.g. binary_sensor for Occupancy_Status)."""

    point_id: str
    site_id: str
    equipment_id: str | None
    external_id: str
    brick_type: str | None
    unit: str | None
    suggested_ha_domain: str = Field(..., description="e.g. binary_sensor, sensor")
    suggested_ha_id: str = Field(..., description="e.g. openfdd_ahu1_occupied")


@router.get("/suggested", response_model=list[SuggestedEntity])
def list_suggested_entities():
    """
    Return suggested Home Assistant entity mappings from points with Brick types.
    E.g. brick_type brick:Occupancy_Status -> binary_sensor.openfdd_<equipment>_occupied.
    Use for HA integration to create binary_sensors for occupancy/schedule logic.
    """
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT p.id, p.site_id, p.equipment_id, p.external_id, p.brick_type, p.unit, e.name AS equipment_name
                FROM points p
                LEFT JOIN equipment e ON p.equipment_id = e.id
                WHERE p.brick_type IS NOT NULL
                ORDER BY p.site_id, p.equipment_id, p.external_id
                """
            )
            rows = cur.fetchall()
    out = []
    for r in rows:
        point_id = str(r["id"])
        site_id = str(r["site_id"])
        equipment_id = str(r["equipment_id"]) if r.get("equipment_id") else None
        external_id = r["external_id"] or ""
        brick_type = r.get("brick_type") or ""
        unit = r.get("unit")
        equipment_name = (r.get("equipment_name") or "unknown").lower().replace(" ", "_")[:32]
        suggested_domain = "sensor"
        suggested_id = f"openfdd_{equipment_name}_{external_id}"[:64]
        if "Occupancy_Status" in brick_type or "occupancy" in brick_type.lower():
            suggested_domain = "binary_sensor"
            suggested_id = f"openfdd_{equipment_name}_occupied"[:64]
        out.append(
            SuggestedEntity(
                point_id=point_id,
                site_id=site_id,
                equipment_id=equipment_id,
                external_id=external_id,
                brick_type=brick_type,
                unit=unit,
                suggested_ha_domain=suggested_domain,
                suggested_ha_id=suggested_id,
            )
        )
    return out
