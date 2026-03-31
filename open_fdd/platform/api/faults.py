"""Fault state and definitions API for HA/Node-RED (binary_sensors)."""

import psycopg2
from fastapi import APIRouter, Query

from open_fdd.platform.database import get_conn
from open_fdd.platform.api.schemas import FaultStateItem, FaultDefinitionItem

router = APIRouter(prefix="/faults", tags=["faults"])


@router.get(
    "/bacnet-devices",
    summary="List BACnet devices from data model (points + equipment)",
)
def list_bacnet_devices(
    site_id: str | None = Query(
        None, description="Filter by site UUID or name; omit for all"
    ),
):
    """
    CRUD/data-model driven: distinct BACnet devices from points (bacnet_device_id not null)
    joined to equipment and sites. For matrix table: one row per device with equipment_type
    for N/A logic (fault equipment_types vs device equipment_type).
    """
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                conditions = ["p.bacnet_device_id IS NOT NULL"]
                params: list = []
                if site_id:
                    conditions.append("(s.id::text = %s OR s.name = %s)")
                    params.extend([site_id, site_id])
                cur.execute(
                    """
                    SELECT DISTINCT ON (s.id, p.bacnet_device_id)
                           s.id AS site_uuid, s.name AS site_name,
                           p.bacnet_device_id, p.equipment_id AS equipment_uuid,
                           e.name AS equipment_name, e.equipment_type
                    FROM points p
                    JOIN sites s ON s.id = p.site_id
                    LEFT JOIN equipment e ON e.id = p.equipment_id
                    WHERE """
                    + " AND ".join(conditions)
                    + """
                    ORDER BY s.id, p.bacnet_device_id, e.name NULLS LAST
                    """,
                    params,
                )
                rows = cur.fetchall()
        return [
            {
                "site_id": str(r["site_uuid"]),
                "site_name": r["site_name"],
                "bacnet_device_id": r["bacnet_device_id"],
                "equipment_id": (
                    str(r["equipment_uuid"]) if r["equipment_uuid"] else None
                ),
                "equipment_name": r["equipment_name"] or "—",
                "equipment_type": r["equipment_type"],
            }
            for r in rows
        ]
    except psycopg2.Error:
        return []


def _fault_state_table_exists(cur) -> bool:
    cur.execute(
        "SELECT 1 FROM information_schema.tables WHERE table_schema = 'public' AND table_name = 'fault_state'"
    )
    return cur.fetchone() is not None


@router.get("/active", response_model=list[FaultStateItem])
def list_active_faults(
    site_id: str | None = Query(None, description="Filter by site_id"),
    equipment_id: str | None = Query(None, description="Filter by equipment_id"),
):
    """
    List currently active fault states (for HA binary_sensors).
    Combine with GET /faults/definitions for labels.
    """
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                if not _fault_state_table_exists(cur):
                    return []
                bacnet_subquery = """
                    (SELECT p.bacnet_device_id FROM points p
                     WHERE p.equipment_id = fs.equipment_id AND p.bacnet_device_id IS NOT NULL
                       AND (p.site_id::text = fs.site_id OR (SELECT s.name FROM sites s WHERE s.id = p.site_id) = fs.site_id)
                     LIMIT 1)
                """
                site_clause = (
                    "(fs.site_id = %s OR fs.site_id IN (SELECT name FROM sites WHERE id::text = %s))"
                )
                if equipment_id and site_id:
                    cur.execute(
                        f"""
                        SELECT fs.id::text, fs.site_id, fs.equipment_id, fs.fault_id, fs.active,
                               fs.last_changed_ts, fs.last_evaluated_ts, fs.context, {bacnet_subquery} AS bacnet_device_id
                        FROM fault_state fs
                        WHERE {site_clause} AND fs.equipment_id = %s AND fs.active = true
                        ORDER BY fs.site_id, fs.equipment_id, fs.fault_id
                        """,
                        (site_id, site_id, equipment_id),
                    )
                elif site_id:
                    cur.execute(
                        f"""
                        SELECT fs.id::text, fs.site_id, fs.equipment_id, fs.fault_id, fs.active,
                               fs.last_changed_ts, fs.last_evaluated_ts, fs.context, {bacnet_subquery} AS bacnet_device_id
                        FROM fault_state fs
                        WHERE {site_clause} AND fs.active = true
                        ORDER BY fs.site_id, fs.equipment_id, fs.fault_id
                        """,
                        (site_id, site_id),
                    )
                else:
                    cur.execute(f"""
                        SELECT fs.id::text, fs.site_id, fs.equipment_id, fs.fault_id, fs.active,
                               fs.last_changed_ts, fs.last_evaluated_ts, fs.context, {bacnet_subquery} AS bacnet_device_id
                        FROM fault_state fs
                        WHERE fs.active = true
                        ORDER BY fs.site_id, fs.equipment_id, fs.fault_id
                        """)
                rows = cur.fetchall()
        return [FaultStateItem.model_validate(dict(r)) for r in rows]
    except psycopg2.Error:
        return []


@router.get("/state", response_model=list[FaultStateItem])
def list_fault_state(
    site_id: str | None = Query(None),
    equipment_id: str | None = Query(
        None, description="Filter by equipment_id (optional with site_id)"
    ),
):
    """List all fault state rows (active and cleared). Use for full state snapshot."""
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                if not _fault_state_table_exists(cur):
                    return []
                bacnet_subquery = """
                    (SELECT p.bacnet_device_id FROM points p
                     WHERE p.equipment_id = fs.equipment_id AND p.bacnet_device_id IS NOT NULL
                       AND (p.site_id::text = fs.site_id OR (SELECT s.name FROM sites s WHERE s.id = p.site_id) = fs.site_id)
                     LIMIT 1)
                """
                site_clause = (
                    "(fs.site_id = %s OR fs.site_id IN (SELECT name FROM sites WHERE id::text = %s))"
                )
                if equipment_id and site_id:
                    cur.execute(
                        f"""
                        SELECT fs.id::text, fs.site_id, fs.equipment_id, fs.fault_id, fs.active,
                               fs.last_changed_ts, fs.last_evaluated_ts, fs.context, {bacnet_subquery} AS bacnet_device_id
                        FROM fault_state fs
                        WHERE {site_clause} AND fs.equipment_id = %s
                        ORDER BY fs.fault_id
                        """,
                        (site_id, site_id, equipment_id),
                    )
                elif site_id:
                    cur.execute(
                        f"""
                        SELECT fs.id::text, fs.site_id, fs.equipment_id, fs.fault_id, fs.active,
                               fs.last_changed_ts, fs.last_evaluated_ts, fs.context, {bacnet_subquery} AS bacnet_device_id
                        FROM fault_state fs
                        WHERE {site_clause}
                        ORDER BY fs.equipment_id, fs.fault_id
                        """,
                        (site_id, site_id),
                    )
                else:
                    cur.execute(f"""
                        SELECT fs.id::text, fs.site_id, fs.equipment_id, fs.fault_id, fs.active,
                               fs.last_changed_ts, fs.last_evaluated_ts, fs.context, {bacnet_subquery} AS bacnet_device_id
                        FROM fault_state fs
                        ORDER BY fs.site_id, fs.equipment_id, fs.fault_id
                        """)
                rows = cur.fetchall()
        return [FaultStateItem.model_validate(dict(r)) for r in rows]
    except psycopg2.Error:
        return []


@router.get("/definitions", response_model=list[FaultDefinitionItem])
def list_fault_definitions():
    """List fault definitions (fault_id, name, severity, category) for HA entity labels."""
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT fault_id, name, description, severity, category, equipment_types
                    FROM fault_definitions
                    ORDER BY category, fault_id
                    """)
                rows = cur.fetchall()
        out = []
        for r in rows:
            out.append(
                FaultDefinitionItem(
                    fault_id=r["fault_id"],
                    name=r["name"],
                    description=r.get("description"),
                    severity=r.get("severity") or "warning",
                    category=r.get("category") or "general",
                    equipment_types=r.get("equipment_types"),
                )
            )
        return out
    except psycopg2.Error:
        return []
