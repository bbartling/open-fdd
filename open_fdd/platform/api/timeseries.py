"""Timeseries API — latest value per point for dashboards (HA, Grafana-style)."""

from datetime import timezone
from typing import Optional

from fastapi import APIRouter, Query

from open_fdd.platform.database import get_conn


def _ts_to_iso_utc(dt):
    """Return ISO string with Z so frontend parses as UTC and displays in local time."""
    if dt is None:
        return None
    if getattr(dt, "tzinfo", None) is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


router = APIRouter(
    prefix="/timeseries",
    tags=["timeseries"],
)


@router.get(
    "/latest",
    summary="Latest value per point (for HA / dashboards)",
    description="Return the most recent reading per point from timeseries_readings (BACnet scraper / weather). "
    "Use for HA sensors or BAS-style dashboards. Optional site_id and equipment_id filter.",
)
def get_timeseries_latest(
    site_id: Optional[str] = Query(None, description="Filter by site UUID or name"),
    equipment_id: Optional[str] = Query(None, description="Filter by equipment UUID"),
):
    """Latest value per point from DB (same data the BACnet scraper writes)."""
    with get_conn() as conn:
        with conn.cursor() as cur:
            # Resolve site to UUID if name given
            site_uuid = None
            if site_id:
                cur.execute(
                    "SELECT id FROM sites WHERE id::text = %s OR name = %s OR description = %s LIMIT 1",
                    (site_id.strip(), site_id.strip(), site_id.strip()),
                )
                row = cur.fetchone()
                if row:
                    site_uuid = str(row["id"])
                else:
                    return []
            eq_uuid = (equipment_id or "").strip() or None
            params = []
            where = []
            if site_uuid:
                where.append("p.site_id = %s")
                params.append(site_uuid)
            if eq_uuid:
                where.append("p.equipment_id = %s")
                params.append(eq_uuid)
            where_sql = " AND ".join(where) if where else "1=1"
            cur.execute(
                f"""
                SELECT DISTINCT ON (tr.point_id)
                    tr.point_id::text AS point_id,
                    p.external_id,
                    p.equipment_id::text AS equipment_id,
                    tr.value,
                    tr.ts
                FROM timeseries_readings tr
                JOIN points p ON tr.point_id = p.id
                WHERE {where_sql}
                ORDER BY tr.point_id, tr.ts DESC
                """,
                tuple(params),
            )
            rows = cur.fetchall()
    return [
        {
            "point_id": r["point_id"],
            "external_id": r["external_id"],
            "equipment_id": r["equipment_id"],
            "value": r["value"],
            "ts": _ts_to_iso_utc(r["ts"]),
        }
        for r in rows
    ]
