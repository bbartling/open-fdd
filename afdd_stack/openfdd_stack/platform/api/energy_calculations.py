"""CRUD for FDD energy / savings calculation specs (DB + TTL knowledge graph)."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Optional
from uuid import UUID

import psycopg2
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from psycopg2.extras import Json

from openfdd_stack.platform.data_model_ttl import sync_ttl_to_file
from openfdd_stack.platform.database import get_conn
from openfdd_stack.platform.energy_calc_library import (
    ALLOWED_CALC_TYPES,
    list_calc_types_public,
    preview_energy_calc,
)
from openfdd_stack.platform.energy_penalty_catalog import (
    PENALTY_CATALOG,
    catalog_rows_for_seed,
)
from openfdd_stack.platform.realtime import TOPIC_CRUD_ENERGY_CALC, emit

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/energy-calculations", tags=["energy-calculations"])


class EnergyCalculationCreate(BaseModel):
    site_id: UUID
    equipment_id: Optional[UUID] = None
    external_id: str = Field(..., min_length=1, max_length=256)
    name: str = Field(..., min_length=1, max_length=256)
    description: Optional[str] = None
    calc_type: str = Field(..., min_length=1, max_length=64)
    parameters: dict[str, Any] = Field(default_factory=dict)
    point_bindings: dict[str, Any] = Field(default_factory=dict)
    enabled: bool = True


class EnergyCalculationUpdate(BaseModel):
    equipment_id: Optional[UUID] = None
    name: Optional[str] = Field(None, min_length=1, max_length=256)
    description: Optional[str] = None
    calc_type: Optional[str] = Field(None, min_length=1, max_length=64)
    parameters: Optional[dict[str, Any]] = None
    point_bindings: Optional[dict[str, Any]] = None
    enabled: Optional[bool] = None


class EnergyCalculationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    site_id: UUID
    equipment_id: Optional[UUID] = None
    external_id: str
    name: str
    description: Optional[str] = None
    calc_type: str
    parameters: dict[str, Any]
    point_bindings: dict[str, Any]
    enabled: bool
    created_at: datetime
    updated_at: datetime


class PreviewBody(BaseModel):
    calc_type: str
    parameters: dict[str, Any] = Field(default_factory=dict)


def _validate_calc_type(ct: str) -> None:
    if ct not in ALLOWED_CALC_TYPES:
        raise HTTPException(
            400,
            f"Unknown calc_type {ct!r}. Use GET /energy-calculations/calc-types.",
        )


_COLS = (
    "id, site_id, equipment_id, external_id, name, description, calc_type, "
    "parameters, point_bindings, enabled, created_at, updated_at"
)


@router.get("/calc-types")
def get_calc_types():
    """Field metadata for Energy Engineering UI dropdowns."""
    return {"calc_types": list_calc_types_public()}


@router.get("/penalty-catalog")
def get_penalty_catalog():
    """
    Open-FDD default FDD energy-penalty narratives (18 rows) ordered by difficulty.
    Use POST /energy-calculations/seed-default-penalty-catalog to materialize disabled
    EnergyCalculation rows for a site.
    """
    return {"penalty_catalog": PENALTY_CATALOG}


@router.get("/export")
def export_energy_calculations(site_id: UUID = Query(..., description="Site UUID to export calcs for.")):
    """
    JSON bundle for LLM-assisted energy engineering: current calcs plus embedded calc_types
    (same shapes as GET /energy-calculations/calc-types) so offline agents have field keys.
    """
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id, name FROM sites WHERE id = %s", (str(site_id),))
            site_row = cur.fetchone()
            if not site_row:
                raise HTTPException(404, "Site not found")
            cur.execute(
                "SELECT "
                + _COLS
                + " FROM energy_calculations\n                    WHERE site_id = %s ORDER BY external_id",
                (str(site_id),),
            )
            calc_rows = cur.fetchall()
            cur.execute(
                "SELECT id, name FROM equipment WHERE site_id = %s ORDER BY name",
                (str(site_id),),
            )
            eq_rows = cur.fetchall()
    eq_name: dict[str, str] = {str(r["id"]): r["name"] for r in eq_rows}
    out_calcs: list[dict[str, Any]] = []
    for r in calc_rows:
        d = dict(r)
        eid = d.get("equipment_id")
        d["equipment_name"] = eq_name.get(str(eid)) if eid else None
        for k in ("id", "site_id", "equipment_id"):
            if d.get(k) is not None:
                d[k] = str(d[k])
        if d.get("created_at"):
            d["created_at"] = d["created_at"].isoformat()
        if d.get("updated_at"):
            d["updated_at"] = d["updated_at"].isoformat()
        out_calcs.append(d)
    return {
        "format": "openfdd_energy_calculations_v1",
        "site_id": str(site_id),
        "site_name": site_row["name"],
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "documentation_hint": "See modeling/ai_assisted_energy_calculations in Open-FDD docs.",
        "calc_types": list_calc_types_public(),
        "penalty_catalog": PENALTY_CATALOG,
        "energy_calculations": out_calcs,
    }


class EnergyCalculationImportRow(BaseModel):
    """One row for PUT /energy-calculations/import (create or update by external_id per site)."""

    model_config = ConfigDict(extra="ignore")

    external_id: str = Field(..., min_length=1, max_length=256)
    name: str = Field(..., min_length=1, max_length=256)
    description: Optional[str] = None
    calc_type: str = Field(..., min_length=1, max_length=64)
    parameters: dict[str, Any] = Field(default_factory=dict)
    point_bindings: dict[str, Any] = Field(default_factory=dict)
    enabled: bool = True
    equipment_id: Optional[UUID] = None
    equipment_name: Optional[str] = Field(
        None,
        description="Resolve equipment under site when equipment_id is omitted.",
    )


class EnergyCalculationsImportBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    site_id: UUID
    energy_calculations: list[EnergyCalculationImportRow]


def _resolve_import_equipment_id(cur, site_id: str, row: EnergyCalculationImportRow) -> Optional[str]:
    if row.equipment_id is not None:
        cur.execute(
            "SELECT id FROM equipment WHERE id = %s AND site_id = %s",
            (str(row.equipment_id), site_id),
        )
        found = cur.fetchone()
        if not found:
            raise HTTPException(
                400,
                f"equipment_id {row.equipment_id} not found for this site",
            )
        return str(found["id"])
    if row.equipment_name and str(row.equipment_name).strip():
        name = str(row.equipment_name).strip()
        cur.execute(
            "SELECT id FROM equipment WHERE site_id = %s AND name = %s",
            (site_id, name),
        )
        matches = cur.fetchall()
        if len(matches) == 0:
            raise HTTPException(
                400,
                f"equipment_name {name!r} not found for site; add equipment in Data Model BRICK first",
            )
        if len(matches) > 1:
            raise HTTPException(400, f"ambiguous equipment_name {name!r}")
        return str(matches[0]["id"])
    return None


@router.put("/import")
def import_energy_calculations(body: EnergyCalculationsImportBody):
    """
    Bulk upsert by (site_id, external_id). Use after LLM fills calc_type, parameters,
    point_bindings, equipment_name from GET /energy-calculations/export.
    """
    sid = str(body.site_id)
    created = 0
    updated = 0
    warnings: list[str] = []
    now = datetime.now(timezone.utc)
    pending_emits: list[tuple[str, dict[str, Any]]] = []
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM sites WHERE id = %s", (sid,))
            if not cur.fetchone():
                raise HTTPException(404, "Site not found")
            for row in body.energy_calculations:
                _validate_calc_type(row.calc_type)
                eq_db_id = _resolve_import_equipment_id(cur, sid, row)
                cur.execute(
                    """SELECT id FROM energy_calculations
                        WHERE site_id = %s AND external_id = %s""",
                    (sid, row.external_id),
                )
                existing = cur.fetchone()
                if existing:
                    cur.execute(
                        """UPDATE energy_calculations SET
                            equipment_id = %s, name = %s, description = %s, calc_type = %s,
                            parameters = %s, point_bindings = %s, enabled = %s, updated_at = %s
                            WHERE id = %s
                            RETURNING id""",
                        (
                            eq_db_id,
                            row.name,
                            row.description,
                            row.calc_type,
                            Json(row.parameters or {}),
                            Json(row.point_bindings or {}),
                            row.enabled,
                            now,
                            str(existing["id"]),
                        ),
                    )
                    cur.fetchone()
                    updated += 1
                    pending_emits.append(
                        (
                            TOPIC_CRUD_ENERGY_CALC + ".updated",
                            {"id": str(existing["id"]), "external_id": row.external_id},
                        )
                    )
                else:
                    cur.execute(
                        """INSERT INTO energy_calculations
                            (site_id, equipment_id, external_id, name, description, calc_type,
                             parameters, point_bindings, enabled, updated_at)
                            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                            RETURNING id""",
                        (
                            sid,
                            eq_db_id,
                            row.external_id,
                            row.name,
                            row.description,
                            row.calc_type,
                            Json(row.parameters or {}),
                            Json(row.point_bindings or {}),
                            row.enabled,
                            now,
                        ),
                    )
                    ins = cur.fetchone()
                    created += 1
                    pending_emits.append(
                        (
                            TOPIC_CRUD_ENERGY_CALC + ".created",
                            {
                                "id": str(ins["id"]),
                                "site_id": sid,
                                "external_id": row.external_id,
                            },
                        )
                    )
        conn.commit()
    for topic, payload in pending_emits:
        emit(topic, payload)
    try:
        sync_ttl_to_file()
    except Exception:
        logger.exception("sync_ttl_to_file failed after energy calculations import")
    return {
        "total": len(body.energy_calculations),
        "created": created,
        "updated": updated,
        "warnings": warnings,
    }


@router.post("/seed-default-penalty-catalog")
def seed_default_penalty_catalog(
    site_id: UUID = Query(..., description="Site to attach catalog rows."),
    replace: bool = Query(
        False,
        description="If true, remove existing penalty_default_* rows for this site, then insert all 18.",
    ),
):
    """
    Insert 18 disabled EnergyCalculation rows (``penalty_default_01`` … ``penalty_default_18``)
    with default parameters and engineering narratives. Enable and bind points in the UI or via import.

    Open-Meteo and utility $/kWh / $/therm remain on platform / site config — single source for weather and rates.
    """
    rows = catalog_rows_for_seed()
    now = datetime.now(timezone.utc)
    created = 0
    deleted = 0
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM sites WHERE id = %s", (str(site_id),))
            if not cur.fetchone():
                raise HTTPException(404, "Site not found")
            if replace:
                cur.execute(
                    """DELETE FROM energy_calculations
                       WHERE site_id = %s AND external_id LIKE 'penalty_default_%%'""",
                    (str(site_id),),
                )
                deleted = cur.rowcount
            for row in rows:
                if not replace:
                    cur.execute(
                        """SELECT id FROM energy_calculations
                           WHERE site_id = %s AND external_id = %s""",
                        (str(site_id), row["external_id"]),
                    )
                    if cur.fetchone():
                        continue
                cur.execute(
                    """INSERT INTO energy_calculations
                        (site_id, equipment_id, external_id, name, description, calc_type,
                         parameters, point_bindings, enabled, updated_at)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                    (
                        str(site_id),
                        None,
                        row["external_id"],
                        row["name"],
                        row["description"],
                        row["calc_type"],
                        Json(row["parameters"]),
                        Json(row["point_bindings"]),
                        row["enabled"],
                        now,
                    ),
                )
                created += 1
        conn.commit()
    try:
        sync_ttl_to_file()
    except Exception:
        logger.exception("sync_ttl_to_file failed after seed penalty catalog")
    return {
        "site_id": str(site_id),
        "created": created,
        "rows_in_catalog": len(rows),
        "deleted_before_insert": deleted if replace else 0,
        "replace": replace,
    }


@router.post("/preview")
def post_preview(body: PreviewBody):
    """Run the calculation library with draft parameters (no DB write)."""
    _validate_calc_type(body.calc_type)
    return preview_energy_calc(body.calc_type, body.parameters)


@router.get("", response_model=list[EnergyCalculationRead])
def list_energy_calculations(
    site_id: UUID | None = None,
    equipment_id: UUID | None = None,
    limit: int = Query(500, ge=1, le=2000),
    offset: int = Query(0, ge=0),
):
    with get_conn() as conn:
        with conn.cursor() as cur:
            if site_id and equipment_id:
                cur.execute(
                    f"""SELECT {_COLS} FROM energy_calculations
                        WHERE site_id = %s AND equipment_id = %s
                        ORDER BY external_id LIMIT %s OFFSET %s""",
                    (str(site_id), str(equipment_id), limit, offset),
                )
            elif equipment_id:
                cur.execute(
                    f"""SELECT {_COLS} FROM energy_calculations
                        WHERE equipment_id = %s ORDER BY external_id LIMIT %s OFFSET %s""",
                    (str(equipment_id), limit, offset),
                )
            elif site_id:
                cur.execute(
                    f"""SELECT {_COLS} FROM energy_calculations
                        WHERE site_id = %s ORDER BY external_id LIMIT %s OFFSET %s""",
                    (str(site_id), limit, offset),
                )
            else:
                cur.execute(
                    f"""SELECT {_COLS} FROM energy_calculations
                        ORDER BY site_id, external_id LIMIT %s OFFSET %s""",
                    (limit, offset),
                )
            rows = cur.fetchall()
    return [EnergyCalculationRead.model_validate(dict(r)) for r in rows]


@router.post("", response_model=EnergyCalculationRead)
def create_energy_calculation(body: EnergyCalculationCreate):
    _validate_calc_type(body.calc_type)
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT "
                + _COLS
                + " FROM energy_calculations\n                    WHERE site_id = %s AND external_id = %s",
                (str(body.site_id), body.external_id),
            )
            existing = cur.fetchone()
            if existing:
                raise HTTPException(
                    409,
                    "Energy calculation with this external_id already exists for this site",
                )
            try:
                cur.execute(
                    "INSERT INTO energy_calculations\n                        (site_id, equipment_id, external_id, name, description, calc_type,\n                         parameters, point_bindings, enabled, updated_at)\n                        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)\n                        RETURNING "
                    + _COLS,
                    (
                        str(body.site_id),
                        str(body.equipment_id) if body.equipment_id else None,
                        body.external_id,
                        body.name,
                        body.description,
                        body.calc_type,
                        Json(body.parameters or {}),
                        Json(body.point_bindings or {}),
                        body.enabled,
                        datetime.now(timezone.utc),
                    ),
                )
                row = cur.fetchone()
            except psycopg2.IntegrityError:
                conn.rollback()
                raise HTTPException(
                    409,
                    "Energy calculation with this external_id already exists for this site",
                ) from None
        conn.commit()
        emit(
            TOPIC_CRUD_ENERGY_CALC + ".created",
            {
                "id": str(row["id"]),
                "site_id": str(row["site_id"]),
                "external_id": row["external_id"],
            },
        )
    try:
        sync_ttl_to_file()
    except Exception:
        logger.exception("sync_ttl_to_file failed after energy calculation create")
    return EnergyCalculationRead.model_validate(dict(row))


@router.get("/{ec_id}", response_model=EnergyCalculationRead)
def get_energy_calculation(ec_id: UUID):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT " + _COLS + " FROM energy_calculations WHERE id = %s",
                (str(ec_id),),
            )
            row = cur.fetchone()
    if not row:
        raise HTTPException(404, "Energy calculation not found")
    return EnergyCalculationRead.model_validate(dict(row))


@router.patch("/{ec_id}", response_model=EnergyCalculationRead)
def update_energy_calculation(ec_id: UUID, body: EnergyCalculationUpdate):
    data = body.model_dump(exclude_unset=True)
    if "calc_type" in data and data["calc_type"] is not None:
        _validate_calc_type(data["calc_type"])
    updates, params = [], []
    if "equipment_id" in data:
        updates.append("equipment_id = %s")
        params.append(str(data["equipment_id"]) if data["equipment_id"] else None)
    if "name" in data:
        updates.append("name = %s")
        params.append(data["name"])
    if "description" in data:
        updates.append("description = %s")
        params.append(data["description"])
    if "calc_type" in data:
        updates.append("calc_type = %s")
        params.append(data["calc_type"])
    if "parameters" in data:
        updates.append("parameters = %s")
        params.append(Json(data["parameters"] if data["parameters"] is not None else {}))
    if "point_bindings" in data:
        updates.append("point_bindings = %s")
        params.append(Json(data["point_bindings"] if data["point_bindings"] is not None else {}))
    if "enabled" in data:
        updates.append("enabled = %s")
        params.append(data["enabled"])
    if not updates:
        return get_energy_calculation(ec_id)
    updates.append("updated_at = %s")
    params.append(datetime.now(timezone.utc))
    params.append(str(ec_id))
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""UPDATE energy_calculations SET {", ".join(updates)} WHERE id = %s
                    RETURNING {_COLS}""",
                params,
            )
            row = cur.fetchone()
        conn.commit()
    if not row:
        raise HTTPException(404, "Energy calculation not found")
    try:
        sync_ttl_to_file()
    except Exception:
        logger.exception("sync_ttl_to_file failed after energy calculation update")
    emit(TOPIC_CRUD_ENERGY_CALC + ".updated", {"id": str(ec_id)})
    return EnergyCalculationRead.model_validate(dict(row))


@router.delete("/{ec_id}")
def delete_energy_calculation(ec_id: UUID):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM energy_calculations WHERE id = %s RETURNING id", (str(ec_id),)
            )
            if not cur.fetchone():
                raise HTTPException(404, "Energy calculation not found")
        conn.commit()
    try:
        sync_ttl_to_file()
    except Exception:
        logger.exception("sync_ttl_to_file failed after energy calculation delete")
    emit(TOPIC_CRUD_ENERGY_CALC + ".deleted", {"id": str(ec_id)})
    return {"status": "deleted"}
