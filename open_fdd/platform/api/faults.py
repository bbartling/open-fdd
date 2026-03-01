"""Fault state and definitions API for HA/Node-RED (binary_sensors)."""

import psycopg2
from fastapi import APIRouter, Query

from open_fdd.platform.database import get_conn
from open_fdd.platform.api.schemas import FaultStateItem, FaultDefinitionItem

router = APIRouter(prefix="/faults", tags=["faults"])


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
                if equipment_id and site_id:
                    cur.execute(
                        """
                        SELECT id::text, site_id, equipment_id, fault_id, active, last_changed_ts, last_evaluated_ts, context
                        FROM fault_state
                        WHERE site_id = %s AND equipment_id = %s AND active = true
                        ORDER BY site_id, equipment_id, fault_id
                        """,
                        (site_id, equipment_id),
                    )
                elif site_id:
                    cur.execute(
                        """
                        SELECT id::text, site_id, equipment_id, fault_id, active, last_changed_ts, last_evaluated_ts, context
                        FROM fault_state
                        WHERE site_id = %s AND active = true
                        ORDER BY site_id, equipment_id, fault_id
                        """,
                        (site_id,),
                    )
                else:
                    cur.execute(
                        """
                        SELECT id::text, site_id, equipment_id, fault_id, active, last_changed_ts, last_evaluated_ts, context
                        FROM fault_state
                        WHERE active = true
                        ORDER BY site_id, equipment_id, fault_id
                        """
                    )
                rows = cur.fetchall()
        return [FaultStateItem.model_validate(dict(r)) for r in rows]
    except psycopg2.Error:
        return []


@router.get("/state", response_model=list[FaultStateItem])
def list_fault_state(
    site_id: str | None = Query(None),
    equipment_id: str | None = Query(None, description="Filter by equipment_id (optional with site_id)"),
):
    """List all fault state rows (active and cleared). Use for full state snapshot."""
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                if not _fault_state_table_exists(cur):
                    return []
                if equipment_id and site_id:
                    cur.execute(
                        """
                        SELECT id::text, site_id, equipment_id, fault_id, active, last_changed_ts, last_evaluated_ts, context
                        FROM fault_state
                        WHERE site_id = %s AND equipment_id = %s
                        ORDER BY fault_id
                        """,
                        (site_id, equipment_id),
                    )
                elif site_id:
                    cur.execute(
                        """
                        SELECT id::text, site_id, equipment_id, fault_id, active, last_changed_ts, last_evaluated_ts, context
                        FROM fault_state
                        WHERE site_id = %s
                        ORDER BY equipment_id, fault_id
                        """,
                        (site_id,),
                    )
                else:
                    cur.execute(
                        """
                        SELECT id::text, site_id, equipment_id, fault_id, active, last_changed_ts, last_evaluated_ts, context
                        FROM fault_state
                        ORDER BY site_id, equipment_id, fault_id
                        """
                    )
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
                cur.execute(
                    """
                    SELECT fault_id, name, description, severity, category, equipment_types
                    FROM fault_definitions
                    ORDER BY category, fault_id
                    """
                )
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
