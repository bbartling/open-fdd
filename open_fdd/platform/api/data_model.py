"""
Data model API: export/import points (JSON for LLM Brick tagging), TTL from DB, SPARQL.

Workflow: Discover BACnet (whois, point_discovery_to_graph) and create/curate points via CRUD.
Export JSON (GET /data-model/export) → LLM or human adds brick_type/rule_input → PUT /data-model/import.
Import only updates BRICK/tagging fields; BACnet refs and point_id are never cleared, so timeseries
and BACnet bindings stay valid. Single source of truth = DB; TTL = DB + in-memory graph (BACnet).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from uuid import UUID

import psycopg2
from fastapi import APIRouter, Body, File, HTTPException, Query, UploadFile
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field

from open_fdd.platform.config import get_platform_settings
from open_fdd.platform.database import get_conn
from open_fdd.platform.data_model_ttl import (
    build_ttl_from_db,
    get_ttl_for_sparql,
    parse_bacnet_ttl_to_discovery,
    sync_ttl_to_file,
)
from open_fdd.platform.graph_model import (
    get_serialization_status,
    get_ttl_path_resolved,
    graph_integrity_check,
    reset_graph_to_db_only,
    serialize_to_ttl,
    write_ttl_to_file,
)

router = APIRouter(prefix="/data-model", tags=["data-model"])


# --- Export: points as JSON (raw names, time-series refs, optional brick_type for LLM to fill) ---


class PointExportRow(BaseModel):
    """One point in the data-model export. point_id is stable for import; BACnet refs identify the device/object."""

    point_id: str
    site_id: str
    site_name: str | None
    external_id: str
    equipment_id: str | None
    equipment_name: str | None
    brick_type: str | None
    rule_input: str | None = Field(
        None,
        description="Name FDD rules use to reference this point's timeseries. Usually = external_id or alias. Maps to DB fdd_input.",
    )
    unit: str | None
    bacnet_device_id: str | None = Field(
        None, description="BACnet device reference; preserved on import."
    )
    object_identifier: str | None = Field(
        None, description="BACnet object ID (e.g. analog-input,1); preserved on import."
    )
    object_name: str | None = Field(
        None, description="BACnet object name; preserved on import."
    )
    polling: bool = Field(
        True,
        description="If true, BACnet scraper polls this point; set false to exclude from scrape. Preserved on import.",
    )


class BacnetExportRow(BaseModel):
    """One BACnet object from discovery (graph). point_id is set if already in DB; omit for new points. Fill site_id, external_id, brick_type, rule_input (and optionally equipment_id) then PUT /data-model/import to create/update points for scraping."""

    point_id: str | None = Field(
        None,
        description="Existing point UUID if already in DB; null for new. Import uses this to update or uses bacnet_device_id+object_identifier+site_id+external_id to create.",
    )
    bacnet_device_id: str = Field(
        ..., description="BACnet device instance (e.g. 3456789)."
    )
    object_identifier: str = Field(
        ..., description="BACnet object (e.g. analog-input,1)."
    )
    object_name: str | None = Field(
        None, description="BACnet object name from discovery."
    )
    site_id: str | None = None
    site_name: str | None = None
    equipment_id: str | None = None
    equipment_name: str | None = None
    external_id: str | None = Field(
        None,
        description="Time-series key; suggest object_name or short id. Required on import for new points.",
    )
    brick_type: str | None = None
    rule_input: str | None = Field(
        None, description="FDD rule reference; maps to fdd_input."
    )
    unit: str | None = None
    polling: bool = Field(
        False,
        description="If true, BACnet scraper polls this point; false by default for unimported objects.",
    )


class UnifiedExportRow(BaseModel):
    """One row in the unified data-model export: BACnet discovery and/or DB points. Use GET /data-model/export for one dump of everything; send to LLM for Brick tagging then PUT /data-model/import."""

    point_id: str | None = Field(
        None,
        description="Point UUID when point exists in DB; null for BACnet-only (not yet imported).",
    )
    bacnet_device_id: str | None = Field(
        None, description="BACnet device instance (e.g. 3456789); null for CRUD-only points."
    )
    object_identifier: str | None = Field(
        None, description="BACnet object (e.g. analog-input,1); null for CRUD-only points."
    )
    object_name: str | None = None
    site_id: str | None = None
    site_name: str | None = None
    equipment_id: str | None = None
    equipment_name: str | None = None
    external_id: str | None = Field(
        None,
        description="Time-series key; required on import for new points.",
    )
    brick_type: str | None = None
    rule_input: str | None = None
    unit: str | None = None
    polling: bool = Field(
        False,
        description="If true, BACnet scraper polls this point; false by default for unimported objects.",
    )


def _build_unified_export(site_id: str | None = None) -> list[UnifiedExportRow]:
    """Single dump: BACnet discovery (graph) + DB points. Rows with no point_id have polling=False by default.
    When site_id query is provided, unimported rows are pre-filled with that site_id and site_name so the JSON
    is closer to ready-to-import (LLM or human only needs to add brick_type, rule_input, equipment_id, polling)."""
    _site_id = _resolve_site_filter(site_id) if (site_id and site_id.strip()) else None
    if site_id and site_id.strip() and _site_id is None:
        raise HTTPException(404, f"No site found for name/description: {site_id!r}")

    default_site_name: str | None = None
    if _site_id:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT name FROM sites WHERE id = %s", (str(_site_id),))
                row = cur.fetchone()
                default_site_name = row["name"] if row else None

    out: list[UnifiedExportRow] = []
    emitted_point_ids: set[str] = set()

    # 1) BACnet objects from graph (with DB overlay when point exists)
    try:
        ttl = serialize_to_ttl()
        _devices, point_discoveries = parse_bacnet_ttl_to_discovery(ttl)
    except Exception:
        point_discoveries = []
    if point_discoveries:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT p.id, p.site_id, s.name AS site_name, p.equipment_id, e.name AS equipment_name,
                           p.external_id, p.brick_type, p.fdd_input, p.unit,
                           p.bacnet_device_id, p.object_identifier, p.object_name,
                           COALESCE(p.polling, true) AS polling
                    FROM points p
                    LEFT JOIN sites s ON s.id = p.site_id
                    LEFT JOIN equipment e ON e.id = p.equipment_id
                    WHERE p.bacnet_device_id IS NOT NULL AND p.object_identifier IS NOT NULL
                    """)
                existing = {
                    (str(r["bacnet_device_id"]), str(r["object_identifier"]).strip()): r
                    for r in cur.fetchall()
                }
        for pd in point_discoveries:
            dev_inst = pd.get("device_instance")
            if dev_inst is None:
                continue
            dev_str = str(dev_inst)
            for obj in pd.get("objects") or []:
                oid = (obj.get("object_identifier") or "").strip()
                oname = (obj.get("object_name") or "").strip() or None
                if not oid:
                    continue
                key = (dev_str, oid)
                row = existing.get(key)
                if _site_id and row and str(row["site_id"]) != str(_site_id):
                    continue
                if row:
                    emitted_point_ids.add(str(row["id"]))
                    out.append(
                        UnifiedExportRow(
                            point_id=str(row["id"]),
                            bacnet_device_id=dev_str,
                            object_identifier=oid,
                            object_name=oname or row.get("object_name"),
                            site_id=str(row["site_id"]) if row.get("site_id") else None,
                            site_name=row.get("site_name"),
                            equipment_id=str(row["equipment_id"]) if row.get("equipment_id") else None,
                            equipment_name=row.get("equipment_name"),
                            external_id=row.get("external_id"),
                            brick_type=row.get("brick_type"),
                            rule_input=row.get("fdd_input"),
                            unit=row.get("unit"),
                            polling=bool(row.get("polling", True)),
                        ),
                    )
                else:
                    out.append(
                        UnifiedExportRow(
                            point_id=None,
                            bacnet_device_id=dev_str,
                            object_identifier=oid,
                            object_name=oname,
                            site_id=str(_site_id) if _site_id else None,
                            site_name=default_site_name,
                            equipment_id=None,
                            equipment_name=None,
                            external_id=oname or oid.replace(",", "_"),
                            brick_type=None,
                            rule_input=None,
                            unit=None,
                            polling=False,
                        ),
                    )

    # 2) DB-only points (not already emitted from BACnet)
    with get_conn() as conn:
        with conn.cursor() as cur:
            if _site_id:
                cur.execute(
                    """
                    SELECT p.id, p.site_id, s.name AS site_name, p.external_id,
                           p.equipment_id, e.name AS equipment_name, p.brick_type, p.fdd_input, p.unit,
                           p.bacnet_device_id, p.object_identifier, p.object_name,
                           COALESCE(p.polling, true) AS polling
                    FROM points p
                    LEFT JOIN sites s ON s.id = p.site_id
                    LEFT JOIN equipment e ON e.id = p.equipment_id
                    WHERE p.site_id = %s
                    ORDER BY p.external_id
                    """,
                    (str(_site_id),),
                )
            else:
                cur.execute("""
                    SELECT p.id, p.site_id, s.name AS site_name, p.external_id,
                           p.equipment_id, e.name AS equipment_name, p.brick_type, p.fdd_input, p.unit,
                           p.bacnet_device_id, p.object_identifier, p.object_name,
                           COALESCE(p.polling, true) AS polling
                    FROM points p
                    LEFT JOIN sites s ON s.id = p.site_id
                    LEFT JOIN equipment e ON e.id = p.equipment_id
                    ORDER BY p.site_id, p.external_id
                    """)
            for r in cur.fetchall():
                pid = str(r["id"])
                if pid in emitted_point_ids:
                    continue
                out.append(
                    UnifiedExportRow(
                        point_id=pid,
                        bacnet_device_id=r.get("bacnet_device_id"),
                        object_identifier=r.get("object_identifier"),
                        object_name=r.get("object_name"),
                        site_id=str(r["site_id"]) if r.get("site_id") else None,
                        site_name=r.get("site_name"),
                        equipment_id=str(r["equipment_id"]) if r.get("equipment_id") else None,
                        equipment_name=r.get("equipment_name"),
                        external_id=r["external_id"],
                        brick_type=r.get("brick_type"),
                        rule_input=r.get("fdd_input"),
                        unit=r.get("unit"),
                        polling=bool(r.get("polling", True)),
                    ),
                )
    return out


@router.get(
    "/export",
    response_model=list[UnifiedExportRow],
    summary="Export data model as JSON (BACnet + DB points for LLM tagging)",
    response_description="One list: BACnet discovery and DB points. Use ?bacnet_only=true to restrict to rows with bacnet_device_id. Rows with point_id null are unimported (polling=false by default). Send to LLM for Brick tagging then PUT /data-model/import.",
)
def export_points(
    site_id: str | None = Query(
        None,
        description="Filter by site (UUID, name, or description). When set, unimported rows are pre-filled with this site_id and site_name so the JSON is closer to ready-to-import.",
    ),
    bacnet_only: bool = Query(
        False,
        description="If true, return only rows that have bacnet_device_id and object_identifier (discovery from graph). Omit or false for full dump (BACnet + CRUD points).",
    ),
):
    """Single export route: BACnet discovery + CRUD points. Use for LLM Brick tagging (docs/appendix/technical_reference, docs/modeling/ai_assisted_tagging); then PUT /data-model/import. Unimported BACnet rows have polling=false by default. Set bacnet_only=true to get only discovery rows."""
    out = _build_unified_export(site_id)
    if bacnet_only:
        out = [r for r in out if r.bacnet_device_id is not None and r.object_identifier is not None]
    return out


# --- Import: bulk update full BRICK data model (points, site, equipment, rule_input) ---


class PointImportRow(BaseModel):
    point_id: str | None = Field(
        None,
        description="Point UUID to update (from GET /data-model/export). Omit with bacnet_device_id+object_identifier+site_id+external_id to create a new point.",
    )
    site_id: str | None = Field(
        None,
        description="Site UUID (GET /sites). Required when creating a point; optional when updating.",
    )
    equipment_id: str | None = Field(
        None, description="Assign point to this equipment (UUID from GET /equipment). Omit and set equipment_name to have import create equipment by name."
    )
    equipment_name: str | None = Field(
        None, description="Equipment name (e.g. AHU-1, VAV-1). When site_id is set and equipment_id is omitted, import creates this equipment under the site and assigns the point to it."
    )
    equipment_type: str | None = Field(
        None, description="Used when creating equipment from equipment_name (e.g. AHU, VAV). Defaults to Equipment."
    )
    external_id: str | None = Field(
        None,
        description="Time-series reference (e.g. HTG-O, ZoneTemp). Required when creating a point.",
    )
    bacnet_device_id: str | None = Field(
        None,
        description="BACnet device instance (e.g. 3456789). Required when creating from export (unimported row).",
    )
    object_identifier: str | None = Field(
        None,
        description="BACnet object (e.g. analog-input,1). Required when creating from export (unimported row).",
    )
    object_name: str | None = Field(None, description="BACnet object name (optional).")
    brick_type: str | None = Field(
        None, description="BRICK class e.g. Supply_Air_Temperature_Sensor"
    )
    rule_input: str | None = Field(
        None,
        description="Name FDD rules use for this point. Usually = external_id (e.g. HTG-O) or alias. Deprecated: fdd_input also accepted.",
    )
    fdd_input: str | None = Field(
        None, description="Deprecated. Use rule_input instead."
    )
    unit: str | None = Field(None, description="e.g. degrees-fahrenheit, percent")
    description: str | None = Field(None, description="Human-readable description")
    polling: bool | None = Field(
        None,
        description="If true, BACnet scraper polls this point; false to exclude from scrape. Omit to leave unchanged (update) or default true (create).",
    )

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "point_id": "a0eebc99-9c0b-4ef8-bb6d-6bb9bd380a11",
                    "brick_type": "Supply_Air_Temperature_Sensor",
                    "rule_input": "sat",
                },
                {
                    "site_id": "<uuid>",
                    "external_id": "SA-T",
                    "bacnet_device_id": "3456789",
                    "object_identifier": "analog-input,2",
                    "object_name": "SA-T",
                    "brick_type": "Supply_Air_Temperature_Sensor",
                    "rule_input": "sat",
                },
            ]
        }
    }


class EquipmentImportRow(BaseModel):
    """Optional equipment relationship updates on import. Use equipment_id (UUID) or equipment_name + site_id (name is created if missing). feeds/fed_by accept UUID or equipment name (resolved under site_id)."""

    equipment_id: str | None = Field(
        None, description="Equipment UUID to update. Omit when using equipment_name + site_id."
    )
    equipment_name: str | None = Field(
        None, description="Equipment name (e.g. AHU-1, VAV-1). With site_id, import finds or creates this equipment then sets feeds/fed_by."
    )
    site_id: str | None = Field(
        None, description="Site UUID. Required when using equipment_name or when feeds_equipment_id/fed_by_equipment_id are equipment names."
    )
    feeds_equipment_id: str | None = Field(
        None, description="Brick: this equipment feeds that one (UUID or equipment name)."
    )
    fed_by_equipment_id: str | None = Field(
        None, description="Brick: this equipment is fed by that one (UUID or equipment name)."
    )
    feeds: list[str] | None = Field(
        None, description="Alias: list of equipment this one feeds (first element used). Use feeds_equipment_id or feeds."
    )
    fed_by: list[str] | None = Field(
        None, description="Alias: list of equipment that feed this one (first element used). Use fed_by_equipment_id or fed_by."
    )


class DataModelImportBody(BaseModel):
    points: list[PointImportRow]
    equipment: list[EquipmentImportRow] = Field(
        default_factory=list,
        description="Optional: update equipment feeds/fed_by; RDF is rebuilt and serialized after import.",
    )

    model_config = {
        "json_schema_extra": {
            "example": {
                "points": [
                    {
                        "point_id": "a0eebc99-9c0b-4ef8-bb6d-6bb9bd380a11",
                        "brick_type": "Supply_Air_Temperature_Sensor",
                        "rule_input": "sat",
                    },
                    {
                        "site_id": "<site-uuid>",
                        "external_id": "ZoneTemp",
                        "bacnet_device_id": "3456790",
                        "object_identifier": "analog-input,1",
                        "object_name": "ZoneTemp",
                        "brick_type": "Zone_Air_Temperature_Sensor",
                        "rule_input": "zt",
                    },
                ]
            }
        }
    }


def _normalize_ttl_id_to_uuid(s: str) -> str | None:
    """If s looks like a TTL local name (site_xxx or eq_xxx with underscores), convert to UUID string (hyphens). Returns None if not in that form."""
    s = (s or "").strip()
    if not s:
        return None
    for prefix in ("site_", "eq_"):
        if s.startswith(prefix) and len(s) > len(prefix):
            tail = s[len(prefix) :].replace("_", "-")
            if len(tail) == 36 and tail.count("-") == 4:  # UUID shape
                try:
                    UUID(tail)
                    return tail
                except (ValueError, TypeError):
                    pass
    return None


def _parse_uuid_or_400(value: str | None, name: str, hint: str = "from GET /sites or GET /equipment") -> UUID | None:
    """Return UUID or raise 400 with a clear message. Accepts UUID or TTL-style ids (e.g. site_262dcf0e_b1ec_42ad_b1eb_14881a1516ab)."""
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    s = value.strip()
    try:
        return UUID(s)
    except (ValueError, TypeError):
        pass
    normalized = _normalize_ttl_id_to_uuid(s)
    if normalized:
        try:
            return UUID(normalized)
        except (ValueError, TypeError):
            pass
    raise HTTPException(
        400,
        f"{name} must be a valid UUID {hint}. Got: {s!r}. (TTL-style ids like site_262dcf0e_b1ec_42ad_... are accepted and converted to UUID.)",
    )


def _normalize_brick_type(s: str | None) -> str | None:
    """Strip brick: prefix if present so brick:Supply_Air_Temperature_Sensor becomes Supply_Air_Temperature_Sensor."""
    if not s or not isinstance(s, str):
        return s
    s = s.strip()
    if s.startswith("brick:"):
        s = s[6:].strip()
    return s or None


def _is_uuid(s: str | None) -> bool:
    if not s or not isinstance(s, str) or not s.strip():
        return False
    try:
        UUID(s.strip())
        return True
    except (ValueError, TypeError):
        return False


def _ensure_equipment(
    cur: Any,
    site_id: UUID,
    name: str,
    equipment_type: str = "Equipment",
) -> str:
    """Find equipment by (site_id, name) or create it. Returns equipment id as string. Same conn/cur so same transaction."""
    name = (name or "").strip()
    if not name:
        raise HTTPException(400, "equipment_name must be non-empty when provided")
    cur.execute(
        "SELECT id FROM equipment WHERE site_id = %s AND name = %s",
        (str(site_id), name),
    )
    row = cur.fetchone()
    if row:
        return str(row["id"])
    cur.execute(
        """INSERT INTO equipment (site_id, name, description, equipment_type, metadata, feeds_equipment_id, fed_by_equipment_id)
           VALUES (%s, %s, NULL, %s, '{}'::jsonb, NULL, NULL)
           RETURNING id""",
        (str(site_id), name, (equipment_type or "Equipment").strip() or "Equipment"),
    )
    row = cur.fetchone()
    return str(row["id"])


def _get_equipment_id_by_name(cur: Any, site_id: UUID, name: str) -> str | None:
    """Look up equipment id by (site_id, name). Returns None if not found."""
    name = (name or "").strip()
    if not name:
        return None
    cur.execute(
        "SELECT id FROM equipment WHERE site_id = %s AND name = %s",
        (str(site_id), name),
    )
    row = cur.fetchone()
    return str(row["id"]) if row else None


@router.put(
    "/import",
    summary="Import Brick mapping (create or update points; preserves BACnet refs)",
    response_description='Count created/updated (e.g. { "created": 5, "updated": 25, "total": 30 }).',
)
def import_data_model(body: DataModelImportBody):
    """Update existing points by point_id, or create new points when point_id is omitted and bacnet_device_id, object_identifier, site_id, external_id are provided (e.g. from GET /data-model/export after LLM tagging). If site_id is null and there is exactly one site in the DB, that site is used. Optional equipment[] updates feeds_equipment_id/fed_by_equipment_id. After all DB updates, RDF is rebuilt from DB and serialized to TTL (in-memory graph + file)."""
    created = 0
    updated = 0
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM sites")
            sites = cur.fetchall()
            default_site_id_str: str | None = str(sites[0]["id"]) if len(sites) == 1 else None
            for row in body.points:
                if row.point_id:
                    # Update existing point
                    updates, params = [], []
                    if row.site_id is not None:
                        updates.append("site_id = %s")
                        params.append(str(_parse_uuid_or_400(row.site_id, "site_id", "from GET /sites")))
                    if row.equipment_id is not None:
                        updates.append("equipment_id = %s")
                        params.append(str(_parse_uuid_or_400(row.equipment_id, "equipment_id", "from GET /equipment")))
                    if row.external_id is not None:
                        updates.append("external_id = %s")
                        params.append(row.external_id)
                    if row.brick_type is not None:
                        updates.append("brick_type = %s")
                        params.append(_normalize_brick_type(row.brick_type))
                    ri = row.rule_input if row.rule_input is not None else row.fdd_input
                    if ri is not None:
                        updates.append("fdd_input = %s")
                        params.append(ri)
                    if row.unit is not None:
                        updates.append("unit = %s")
                        params.append(row.unit)
                    if row.description is not None:
                        updates.append("description = %s")
                        params.append(row.description)
                    if row.polling is not None:
                        updates.append("polling = %s")
                        params.append(row.polling)
                    if updates:
                        params.append(row.point_id)
                        cur.execute(
                            f"""UPDATE points SET {", ".join(updates)} WHERE id = %s""",
                            params,
                        )
                        if cur.rowcount:
                            updated += 1
                else:
                    # Create new point: require site_id (or default when exactly one site), external_id, bacnet_device_id, object_identifier
                    effective_site_id = row.site_id if (row.site_id and str(row.site_id).strip()) else default_site_id_str
                    if not all(
                        [
                            effective_site_id,
                            row.external_id,
                            row.bacnet_device_id,
                            row.object_identifier,
                        ]
                    ):
                        continue
                    site_uuid = _parse_uuid_or_400(effective_site_id, "site_id", "from GET /sites or use GET /data-model/export?site_id=YourSite to pre-fill")
                    if row.equipment_id:
                        equip_uuid_str = str(_parse_uuid_or_400(row.equipment_id, "equipment_id", "from GET /equipment"))
                    elif row.equipment_name:
                        equip_uuid_str = _ensure_equipment(cur, site_uuid, row.equipment_name, row.equipment_type or "Equipment")
                    else:
                        equip_uuid_str = None
                    _polling = row.polling if row.polling is not None else True
                    _brick = _normalize_brick_type(row.brick_type)
                    _fdd = (
                        row.rule_input
                        if row.rule_input is not None
                        else row.fdd_input
                    )
                    insert_params = (
                        str(site_uuid),
                        row.external_id,
                        row.bacnet_device_id,
                        row.object_identifier,
                        row.object_name,
                        equip_uuid_str,
                        _brick,
                        _fdd,
                        row.unit,
                        row.description,
                        _polling,
                    )
                    try:
                        cur.execute("SAVEPOINT point_import_insert")
                        cur.execute(
                            """INSERT INTO points (site_id, external_id, bacnet_device_id, object_identifier, object_name, equipment_id, brick_type, fdd_input, unit, description, polling)
                               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                            insert_params,
                        )
                        if cur.rowcount:
                            created += 1
                    except psycopg2.IntegrityError as e:
                        if e.pgcode != "23505":
                            raise
                        # UniqueViolation (site_id, external_id): roll back failed INSERT then update existing row (same transaction stays valid)
                        cur.execute("ROLLBACK TO SAVEPOINT point_import_insert")
                        cur.execute(
                            """UPDATE points SET bacnet_device_id = %s, object_identifier = %s, object_name = %s, equipment_id = %s, brick_type = %s, fdd_input = %s, unit = %s, description = %s, polling = %s
                               WHERE site_id = %s AND external_id = %s""",
                            (
                                row.bacnet_device_id,
                                row.object_identifier,
                                row.object_name,
                                equip_uuid_str,
                                _brick,
                                _fdd,
                                row.unit,
                                row.description,
                                _polling,
                                str(site_uuid),
                                row.external_id,
                            ),
                        )
                        if cur.rowcount:
                            updated += 1
            for eq in body.equipment:
                effective_eq_site_id = eq.site_id if (eq.site_id and str(eq.site_id).strip()) else default_site_id_str
                if eq.equipment_id:
                    eq_id = str(_parse_uuid_or_400(eq.equipment_id, "equipment_id", "from GET /equipment (equipment array)"))
                elif eq.equipment_name and effective_eq_site_id:
                    site_uuid_eq = _parse_uuid_or_400(effective_eq_site_id, "site_id", "from GET /sites (equipment array)")
                    eq_id = _ensure_equipment(cur, site_uuid_eq, eq.equipment_name, "Equipment")
                else:
                    continue  # skip row without equipment_id or (equipment_name + site_id)
                site_uuid_for_names = _parse_uuid_or_400(effective_eq_site_id, "site_id", "from GET /sites") if effective_eq_site_id else None
                feeds_val = eq.feeds_equipment_id or (eq.feeds[0] if getattr(eq, "feeds", None) else None)
                fed_by_val = eq.fed_by_equipment_id or (eq.fed_by[0] if getattr(eq, "fed_by", None) else None)
                updates, params = [], []
                if feeds_val is not None:
                    updates.append("feeds_equipment_id = %s::uuid")
                    if _is_uuid(feeds_val):
                        params.append(str(_parse_uuid_or_400(feeds_val, "feeds_equipment_id", "from GET /equipment")))
                    elif site_uuid_for_names:
                        fid = _get_equipment_id_by_name(cur, site_uuid_for_names, feeds_val)
                        if not fid:
                            raise HTTPException(400, f"Equipment name {feeds_val!r} not found for site (create equipment first or use UUID).")
                        params.append(fid)
                    else:
                        raise HTTPException(400, "site_id required in equipment array when feeds_equipment_id is an equipment name.")
                if fed_by_val is not None:
                    updates.append("fed_by_equipment_id = %s::uuid")
                    if _is_uuid(fed_by_val):
                        params.append(str(_parse_uuid_or_400(fed_by_val, "fed_by_equipment_id", "from GET /equipment")))
                    elif site_uuid_for_names:
                        fid = _get_equipment_id_by_name(cur, site_uuid_for_names, fed_by_val)
                        if not fid:
                            raise HTTPException(400, f"Equipment name {fed_by_val!r} not found for site (create equipment first or use UUID).")
                        params.append(fid)
                    else:
                        raise HTTPException(400, "site_id required in equipment array when fed_by_equipment_id is an equipment name.")
                if updates:
                    params.append(eq_id)
                    cur.execute(
                        f"""UPDATE equipment SET {", ".join(updates)} WHERE id = %s""",
                        params,
                    )
        conn.commit()
    try:
        sync_ttl_to_file()
    except Exception:
        pass
    return {"created": created, "updated": updated, "total": len(body.points)}


# --- TTL: generate from DB (always in sync with CRUD) ---


def _resolve_site_filter(site_filter: str | None) -> UUID | None:
    """Resolve site_id param: UUID, site name, or description. Returns None if empty. Omit param for all sites."""
    if not site_filter or not site_filter.strip():
        return None
    s = site_filter.strip()
    try:
        return UUID(s)
    except ValueError:
        pass
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT id FROM sites WHERE name ILIKE %s OR description ILIKE %s LIMIT 1""",
                (s, s),
            )
            row = cur.fetchone()
    return UUID(str(row["id"])) if row else None


@router.get(
    "/ttl",
    response_class=PlainTextResponse,
    summary="View Brick + BACnet TTL",
    response_description="Turtle (text/turtle) of current data model (DB + in-memory graph).",
)
def get_ttl(
    site_id: str | None = Query(
        None,
        description="Filter by site: UUID, site name (e.g. BensOffice), or description. Omit for all sites.",
    ),
    save: bool = Query(
        True,
        description="Write TTL to config/data_model.ttl (default: true). Also auto-synced on every CRUD/import.",
    ),
):
    """Return full data model TTL (Brick from DB + BACnet from in-memory graph). Omit for all sites."""
    _site_id = _resolve_site_filter(site_id)
    if site_id and site_id.strip() and _site_id is None:
        raise HTTPException(404, f"No site found for name/description: {site_id!r}")
    try:
        ttl = serialize_to_ttl()
    except Exception:
        ttl = build_ttl_from_db(site_id=_site_id)
    if save:
        try:
            ok, err = write_ttl_to_file()
            if not ok and err:
                resp = PlainTextResponse(ttl, media_type="text/turtle")
                resp.headers["X-TTL-Save"] = "failed"
                resp.headers["X-TTL-Save-Error"] = (err or "")[:200]
                return resp
        except Exception as e:
            resp = PlainTextResponse(ttl, media_type="text/turtle")
            resp.headers["X-TTL-Save"] = "failed"
            resp.headers["X-TTL-Save-Error"] = str(e)[:200]
            return resp
    return PlainTextResponse(ttl, media_type="text/turtle")


# --- Serialize: write in-memory graph to config/data_model.ttl (same as interval job) ---


@router.post(
    "/serialize",
    summary="Serialize graph to TTL file",
    response_description="Status and path; same function runs on the background interval.",
)
def serialize_graph_to_file():
    """Serialize the in-memory graph (Brick + BACnet + config) to config/data_model.ttl. Same as the 5‑minute background sync."""
    ok, err = write_ttl_to_file()
    status = get_serialization_status()
    resolved_path = get_ttl_path_resolved()
    if ok:
        return {
            "status": "ok",
            "path": str(get_platform_settings().brick_ttl_path),
            "path_resolved": resolved_path,
            **status["graph_serialization"],
        }
    return {
        "status": "error",
        "error": err,
        "path_resolved": resolved_path,
        **status["graph_serialization"],
    }


# --- Check: integrity and orphan detection ---


@router.get(
    "/check",
    summary="Data model integrity check",
    response_description="Triple counts, orphan blank nodes, warnings.",
)
def data_model_check():
    """Run integrity checks on the in-memory graph. Flags orphan blank nodes (e.g. leftover device-address nodes from old TTL). Use POST /data-model/reset to clear graph to DB-only and remove orphans."""
    return graph_integrity_check()


# --- Reset: clear graph to DB-only (removes BACnet and orphans), then serialize ---


@router.post(
    "/reset",
    summary="Reset graph to DB-only (clear BACnet and orphans; Brick repopulated from DB)",
    response_description="Status; graph is Brick-only after reset, file rewritten.",
)
def data_model_reset():
    """Clear the in-memory graph and repopulate from DB only (Brick). Removes all BACnet triples and orphaned blank nodes, then writes config/data_model.ttl. Brick triples come from the database—so if the DB still has sites/equipment/points, the TTL will still contain them. To get an empty data model: delete all sites via CRUD (DELETE /sites/{id} for each; cascade removes equipment and points), then POST /data-model/reset."""
    reset_graph_to_db_only()
    ok, err = write_ttl_to_file()
    status = get_serialization_status()
    if ok:
        return {
            "status": "ok",
            "path": str(get_platform_settings().brick_ttl_path),
            "message": "Graph reset to DB-only. BACnet and orphans removed; Brick repopulated from database (TTL still has whatever sites/equipment/points exist in DB). To empty the model, delete all sites via CRUD first, then reset.",
            **status["graph_serialization"],
        }
    return {
        "status": "error",
        "error": err,
        **status["graph_serialization"],
    }


# --- SPARQL: run query against current TTL (from DB) ---


class SparqlRequest(BaseModel):
    query: str = Field(
        ...,
        description="SPARQL query to run against the current data model (TTL from DB).",
    )

    model_config = {
        "json_schema_extra": {
            "example": {
                "query": "PREFIX brick: <https://brickschema.org/schema/Brick#>\n"
                "PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>\n"
                "SELECT ?site ?site_label WHERE { ?site a brick:Site . ?site rdfs:label ?site_label }"
            }
        }
    }


def _run_sparql_on_ttl(ttl_content: str, query: str) -> list[dict]:
    try:
        from rdflib import Graph
    except ImportError:
        raise HTTPException(
            503,
            "rdflib required. Install: pip install open-fdd[brick]",
        ) from None
    g = Graph()
    try:
        g.parse(data=ttl_content, format="turtle")
    except Exception as e:
        raise HTTPException(400, f"Invalid TTL: {e}") from e
    try:
        results = g.query(query)
    except Exception as e:
        raise HTTPException(400, f"SPARQL error: {e}") from e
    bindings = []
    for row in results:
        bindings.append(
            {str(k): str(v) if v is not None else None for k, v in row.asdict().items()}
        )
    return bindings


@router.post(
    "/sparql",
    summary="Run SPARQL (validate)",
    response_description="Query result bindings as JSON.",
)
def run_sparql(
    body: SparqlRequest = Body(
        ...,
        examples=[
            {
                "query": "PREFIX brick: <https://brickschema.org/schema/Brick#>\n"
                "PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>\n"
                "SELECT ?site ?site_label WHERE { ?site a brick:Site . ?site rdfs:label ?site_label }"
            }
        ],
    ),
):
    """Run a SPARQL query **right here in Swagger**: use the example body or paste your own query, then **Try it out** → Execute. The query runs against the current data model (TTL from DB merged with BACnet scan when present). Returns bindings as JSON. Use to validate time-series refs, BRICK mapping, no orphans. For .sparql files use POST /data-model/sparql/upload."""
    ttl = get_ttl_for_sparql()
    return {"bindings": _run_sparql_on_ttl(ttl, body.query)}


@router.post(
    "/sparql/upload",
    summary="Run a .sparql file",
    response_description="Query result bindings as JSON.",
)
async def run_sparql_upload(
    file: UploadFile = File(
        ...,
        description="Upload a .sparql file (e.g. from analyst/sparql/). Same as POST /sparql with the file contents as query.",
    ),
):
    """Upload a .sparql file to run against the current data model. Use when you have saved queries (e.g. analyst/sparql/05_site_and_counts.sparql). For ad‑hoc queries use POST /data-model/sparql and type the query in Swagger."""
    if not file.filename or not file.filename.lower().endswith(".sparql"):
        raise HTTPException(400, "Upload a .sparql file")
    query = (await file.read()).decode("utf-8")
    ttl = get_ttl_for_sparql()
    return {"bindings": _run_sparql_on_ttl(ttl, query)}
