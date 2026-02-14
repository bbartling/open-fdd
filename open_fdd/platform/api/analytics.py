"""Fault analytics API — data-model driven, motor runtime, fault summary.

If the data model has no fan/VFD point for motor runtime, returns NO DATA.
For MSI/cloud integrators and Grafana (via JSON datasource or downstream ETL).
"""

from datetime import date, datetime, timedelta
from typing import Any, Optional

import pandas as pd
from fastapi import APIRouter, HTTPException, Query

from open_fdd.platform.config import get_platform_settings
from open_fdd.platform.database import get_conn
from open_fdd.platform.site_resolver import resolve_site_uuid

router = APIRouter(prefix="/analytics", tags=["analytics"])

# Brick types that indicate fan/VFD for motor runtime (data-model driven)
MOTOR_BRICK_PATTERNS = (
    "%Fan%Status%",
    "%Fan%Speed%",
    "%Fan%Command%",
    "%VFD%",
    "%Variable_Frequency_Drive%",
)


def _motor_point_for_site(site_uuid: str) -> Optional[dict]:
    """Find first fan/VFD point for site from data model. Returns None if none."""
    with get_conn() as conn:
        with conn.cursor() as cur:
            conditions = " OR ".join(
                ["p.brick_type ILIKE %s"] * len(MOTOR_BRICK_PATTERNS)
            )
            cur.execute(
                f"""
                SELECT p.id, p.external_id, p.brick_type
                FROM points p
                WHERE p.site_id = %s AND ({conditions})
                LIMIT 1
                """,
                (str(site_uuid),) + MOTOR_BRICK_PATTERNS,
            )
            row = cur.fetchone()
    return dict(row) if row else None


def _motor_runtime_hours(point_id: str, start_ts: datetime, end_ts: datetime) -> float:
    """Compute motor runtime (hours) from timeseries where value > 0.01."""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT ts, value FROM timeseries_readings
                WHERE point_id = %s AND ts >= %s AND ts <= %s
                ORDER BY ts
                """,
                (point_id, start_ts, end_ts),
            )
            rows = cur.fetchall()
    if not rows or len(rows) < 2:
        return 0.0
    df = pd.DataFrame(rows)
    df["ts"] = pd.to_datetime(df["ts"])
    df = df.set_index("ts").sort_index()
    delta = df.index.to_series().diff()
    motor_on = df["value"].gt(0.01).astype(int)
    hours = (delta * motor_on).sum() / pd.Timedelta(hours=1)
    return round(float(hours), 2)


@router.get("/motor-runtime", summary="Motor runtime (data-model driven)")
def get_motor_runtime(
    site_id: str = Query(..., description="Site name or UUID"),
    start_date: date = Query(..., description="Start of range"),
    end_date: date = Query(..., description="End of range"),
):
    """
    **Data-model driven:** If no fan/VFD point in the data model, returns NO DATA.
    Otherwise returns motor runtime hours (sum of intervals when fan speed/status > 0.01).
    For MSI/cloud: poll this for runtime analytics. Grafana: use JSON datasource or ETL.
    """
    site_uuid = resolve_site_uuid(site_id, create_if_empty=False)
    if site_uuid is None:
        raise HTTPException(404, f"No site found for: {site_id!r}")

    point = _motor_point_for_site(str(site_uuid))
    if not point:
        return {
            "site_id": site_id,
            "motor_runtime_hours": None,
            "status": "NO DATA",
            "reason": "No fan/VFD point in data model (brick_type: Supply_Fan_Status, Supply_Fan_Speed_Command, etc.)",
        }

    start_ts = datetime.combine(start_date, datetime.min.time())
    end_ts = datetime.combine(end_date, datetime.max.time())

    hours = _motor_runtime_hours(str(point["id"]), start_ts, end_ts)

    # Cache for Grafana (queries analytics_motor_runtime table)
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO analytics_motor_runtime
                      (site_id, period_start, period_end, runtime_hours, point_external_id, point_brick_type, updated_at)
                    VALUES (%s, %s, %s, %s, %s, %s, now())
                    ON CONFLICT (site_id, period_start, period_end) DO UPDATE SET
                      runtime_hours = EXCLUDED.runtime_hours,
                      point_external_id = EXCLUDED.point_external_id,
                      point_brick_type = EXCLUDED.point_brick_type,
                      updated_at = now()
                    """,
                    (site_id, start_date, end_date, hours, point["external_id"], point["brick_type"]),
                )
                conn.commit()
    except Exception:
        pass  # Table may not exist yet; API still returns correct JSON

    return {
        "site_id": site_id,
        "motor_runtime_hours": hours,
        "point": {
            "external_id": point["external_id"],
            "brick_type": point["brick_type"],
        },
        "period": {"start": str(start_date), "end": str(end_date)},
    }


@router.get("/fault-summary", summary="Fault summary by fault_id")
def get_fault_summary(
    site_id: Optional[str] = Query(None, description="Site name or UUID; omit for all"),
    start_date: date = Query(..., description="Start of range"),
    end_date: date = Query(..., description="End of range"),
):
    """
    Fault counts by fault_id. For MSI/cloud and Grafana JSON datasource.
    Combine with /analytics/motor-runtime for full fault analytics.
    """
    conditions = ["ts::date >= %s", "ts::date <= %s"]
    params: list = [start_date, end_date]
    if site_id:
        if resolve_site_uuid(site_id, create_if_empty=False) is None:
            raise HTTPException(404, f"No site found for: {site_id!r}")
        conditions.append("site_id = %s")
        params.append(site_id)

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT fault_id, COUNT(*) AS count, SUM(flag_value) AS flag_sum
                FROM fault_results
                WHERE {" AND ".join(conditions)}
                GROUP BY fault_id
                ORDER BY flag_sum DESC
                """,
                params,
            )
            rows = cur.fetchall()

    by_fault = [{"fault_id": r["fault_id"], "count": r["count"], "flag_sum": r["flag_sum"]} for r in rows]
    return {
        "site_id": site_id,
        "period": {"start": str(start_date), "end": str(end_date)},
        "by_fault_id": by_fault,
        "total_faults": sum(r["flag_sum"] for r in rows),
    }
