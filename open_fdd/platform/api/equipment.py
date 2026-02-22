"""Equipment CRUD API."""

import json
from uuid import UUID

from fastapi import APIRouter, HTTPException

from open_fdd.platform.database import get_conn
from open_fdd.platform.data_model_ttl import sync_ttl_to_file
from open_fdd.platform.api.models import EquipmentCreate, EquipmentRead, EquipmentUpdate

router = APIRouter(prefix="/equipment", tags=["equipment"])


@router.get("", response_model=list[EquipmentRead])
def list_equipment(site_id: UUID | None = None):
    """List equipment, optionally filtered by site."""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cols = "id, site_id, name, description, equipment_type, feeds_equipment_id, fed_by_equipment_id, created_at"
            if site_id:
                cur.execute(
                    f"SELECT {cols} FROM equipment WHERE site_id = %s ORDER BY name",
                    (str(site_id),),
                )
            else:
                cur.execute(
                    f"SELECT {cols} FROM equipment ORDER BY site_id, name"
                )
            rows = cur.fetchall()
    return [EquipmentRead.model_validate(dict(r)) for r in rows]


@router.post("", response_model=EquipmentRead)
def create_equipment(body: EquipmentCreate):
    """Create equipment under a site. Returns 409 if this site already has equipment with this name."""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id FROM equipment WHERE site_id = %s AND name = %s",
                (str(body.site_id), body.name.strip()),
            )
            if cur.fetchone():
                raise HTTPException(
                    409,
                    "Equipment with this name already exists for this site",
                )
            cur.execute(
                """INSERT INTO equipment (site_id, name, description, equipment_type, metadata, feeds_equipment_id, fed_by_equipment_id)
                   VALUES (%s, %s, %s, %s, %s::jsonb, %s::uuid, %s::uuid)
                   RETURNING id, site_id, name, description, equipment_type, feeds_equipment_id, fed_by_equipment_id, created_at""",
                (
                    str(body.site_id),
                    body.name,
                    body.description,
                    body.equipment_type,
                    json.dumps(body.metadata_ or {}),
                    str(body.feeds_equipment_id) if body.feeds_equipment_id else None,
                    str(body.fed_by_equipment_id) if body.fed_by_equipment_id else None,
                ),
            )
            row = cur.fetchone()
        conn.commit()
    try:
        sync_ttl_to_file()
    except Exception:
        pass
    return EquipmentRead.model_validate(dict(row))


@router.get("/{equipment_id}", response_model=EquipmentRead)
def get_equipment(equipment_id: UUID):
    """Get equipment by ID."""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, site_id, name, description, equipment_type, feeds_equipment_id, fed_by_equipment_id, created_at FROM equipment WHERE id = %s",
                (str(equipment_id),),
            )
            row = cur.fetchone()
    if not row:
        raise HTTPException(404, "Equipment not found")
    return EquipmentRead.model_validate(dict(row))


@router.patch("/{equipment_id}", response_model=EquipmentRead)
def update_equipment(equipment_id: UUID, body: EquipmentUpdate):
    """Update equipment."""
    updates, params = [], []
    if body.name is not None:
        updates.append("name = %s")
        params.append(body.name)
    if body.description is not None:
        updates.append("description = %s")
        params.append(body.description)
    if body.equipment_type is not None:
        updates.append("equipment_type = %s")
        params.append(body.equipment_type)
    if body.metadata_ is not None:
        updates.append("metadata = %s::jsonb")
        params.append(json.dumps(body.metadata_))
    if body.feeds_equipment_id is not None:
        updates.append("feeds_equipment_id = %s::uuid")
        params.append(str(body.feeds_equipment_id))
    if body.fed_by_equipment_id is not None:
        updates.append("fed_by_equipment_id = %s::uuid")
        params.append(str(body.fed_by_equipment_id))
    if not updates:
        return get_equipment(equipment_id)
    if body.name is not None:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT id, site_id FROM equipment WHERE id = %s",
                    (str(equipment_id),),
                )
                existing = cur.fetchone()
                if existing:
                    cur.execute(
                        "SELECT id FROM equipment WHERE site_id = %s AND name = %s AND id != %s",
                        (str(existing["site_id"]), body.name.strip(), str(equipment_id)),
                    )
                    if cur.fetchone():
                        raise HTTPException(
                            409,
                            "Another equipment with this name already exists for this site",
                        )
    params.append(str(equipment_id))
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"UPDATE equipment SET {', '.join(updates)} WHERE id = %s RETURNING id, site_id, name, description, equipment_type, feeds_equipment_id, fed_by_equipment_id, created_at",
                params,
            )
            row = cur.fetchone()
        conn.commit()
    if not row:
        raise HTTPException(404, "Equipment not found")
    try:
        sync_ttl_to_file()
    except Exception:
        pass
    return EquipmentRead.model_validate(dict(row))


@router.delete("/{equipment_id}")
def delete_equipment(equipment_id: UUID):
    """Delete equipment and its points (cascade)."""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM equipment WHERE id = %s RETURNING id", (str(equipment_id),)
            )
            if not cur.fetchone():
                raise HTTPException(404, "Equipment not found")
        conn.commit()
    try:
        sync_ttl_to_file()
    except Exception:
        pass
    return {"status": "deleted"}
