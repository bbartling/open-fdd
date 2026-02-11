"""Points CRUD API — data model for timeseries references."""

from uuid import UUID

from fastapi import APIRouter, HTTPException

from open_fdd.platform.database import get_conn
from open_fdd.platform.data_model_ttl import sync_ttl_to_file
from open_fdd.platform.api.models import PointCreate, PointRead, PointUpdate

router = APIRouter(prefix="/points", tags=["points"])


@router.get("", response_model=list[PointRead])
def list_points(site_id: UUID | None = None, equipment_id: UUID | None = None):
    """List points, optionally filtered by site or equipment."""
    with get_conn() as conn:
        with conn.cursor() as cur:
            if equipment_id:
                cur.execute(
                    """SELECT id, site_id, external_id, brick_type, fdd_input, unit, description, equipment_id, created_at
                       FROM points WHERE equipment_id = %s ORDER BY external_id""",
                    (str(equipment_id),),
                )
            elif site_id:
                cur.execute(
                    """SELECT id, site_id, external_id, brick_type, fdd_input, unit, description, equipment_id, created_at
                       FROM points WHERE site_id = %s ORDER BY external_id""",
                    (str(site_id),),
                )
            else:
                cur.execute(
                    """SELECT id, site_id, external_id, brick_type, fdd_input, unit, description, equipment_id, created_at
                       FROM points ORDER BY site_id, external_id"""
                )
            rows = cur.fetchall()
    return [PointRead.model_validate(dict(r)) for r in rows]


@router.post("", response_model=PointRead)
def create_point(body: PointCreate):
    """Create a point."""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO points (site_id, external_id, brick_type, fdd_input, unit, description, equipment_id)
                   VALUES (%s, %s, %s, %s, %s, %s, %s)
                   RETURNING id, site_id, external_id, brick_type, fdd_input, unit, description, equipment_id, created_at""",
                (
                    str(body.site_id),
                    body.external_id,
                    body.brick_type,
                    body.fdd_input,
                    body.unit,
                    body.description,
                    str(body.equipment_id) if body.equipment_id else None,
                ),
            )
            row = cur.fetchone()
        conn.commit()
    try:
        sync_ttl_to_file()
    except Exception:
        pass
    return PointRead.model_validate(dict(row))


@router.get("/{point_id}", response_model=PointRead)
def get_point(point_id: UUID):
    """Get a point by ID."""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT id, site_id, external_id, brick_type, fdd_input, unit, description, equipment_id, created_at
                   FROM points WHERE id = %s""",
                (str(point_id),),
            )
            row = cur.fetchone()
    if not row:
        raise HTTPException(404, "Point not found")
    return PointRead.model_validate(dict(row))


@router.patch("/{point_id}", response_model=PointRead)
def update_point(point_id: UUID, body: PointUpdate):
    """Update a point."""
    updates, params = [], []
    if body.brick_type is not None:
        updates.append("brick_type = %s")
        params.append(body.brick_type)
    if body.fdd_input is not None:
        updates.append("fdd_input = %s")
        params.append(body.fdd_input)
    if body.unit is not None:
        updates.append("unit = %s")
        params.append(body.unit)
    if body.description is not None:
        updates.append("description = %s")
        params.append(body.description)
    if body.equipment_id is not None:
        updates.append("equipment_id = %s")
        params.append(str(body.equipment_id))
    if not updates:
        return get_point(point_id)
    params.append(str(point_id))
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""UPDATE points SET {', '.join(updates)} WHERE id = %s
                    RETURNING id, site_id, external_id, brick_type, fdd_input, unit, description, equipment_id, created_at""",
                params,
            )
            row = cur.fetchone()
        conn.commit()
    if not row:
        raise HTTPException(404, "Point not found")
    try:
        sync_ttl_to_file()
    except Exception:
        pass
    return PointRead.model_validate(dict(row))


@router.delete("/{point_id}")
def delete_point(point_id: UUID):
    """Delete a point and its timeseries (cascade)."""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM points WHERE id = %s RETURNING id", (str(point_id),)
            )
            if not cur.fetchone():
                raise HTTPException(404, "Point not found")
        conn.commit()
    try:
        sync_ttl_to_file()
    except Exception:
        pass
    return {"status": "deleted"}
