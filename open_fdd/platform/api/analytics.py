"""Fault analytics API — data-model driven, motor runtime, fault summary.

If the data model has no fan/VFD point for motor runtime, returns NO DATA.
For MSI/cloud integrators and Grafana (via JSON datasource or downstream ETL).
"""

from datetime import date, datetime, timedelta, timezone
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
                    (
                        site_id,
                        start_date,
                        end_date,
                        hours,
                        point["external_id"],
                        point["brick_type"],
                    ),
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
    active_in_period = count of distinct (site, equipment, fault) that were active (flag_value=1)
    in the range; not summed. total_faults kept for chart compatibility (sum of flag_value).
    """
    conditions = ["ts::date >= %s", "ts::date <= %s"]
    params: list = [start_date, end_date]
    if site_id:
        if resolve_site_uuid(site_id, create_if_empty=False) is None:
            raise HTTPException(404, f"No site found for: {site_id!r}")
        conditions.append("(site_id = %s OR site_id IN (SELECT name FROM sites WHERE id::text = %s))")
        params.extend([site_id, site_id])

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
            # Active-in-period: distinct (site_id, equipment_id, fault_id) with at least one flag_value=1 in range
            active_conditions = [
                "ts::date >= %s",
                "ts::date <= %s",
                "flag_value = 1",
            ]
            active_params: list = [start_date, end_date]
            if site_id:
                active_conditions.append(
                    "(site_id = %s OR site_id IN (SELECT name FROM sites WHERE id::text = %s))"
                )
                active_params.extend([site_id, site_id])
            cur.execute(
                f"""
                SELECT COUNT(*) AS n FROM (
                    SELECT 1 FROM fault_results
                    WHERE {" AND ".join(active_conditions)}
                    GROUP BY site_id, equipment_id, fault_id
                ) sub
                """,
                active_params,
            )
            active_row = cur.fetchone()
    active_in_period = int(active_row["n"]) if active_row else 0

    by_fault = [
        {"fault_id": r["fault_id"], "count": r["count"], "flag_sum": r["flag_sum"]}
        for r in rows
    ]
    return {
        "site_id": site_id,
        "period": {"start": str(start_date), "end": str(end_date)},
        "by_fault_id": by_fault,
        "total_faults": sum(r["flag_sum"] for r in rows),
        "active_in_period": active_in_period,
    }


@router.get("/fault-timeseries", summary="Fault flags over time (for charts)")
def get_fault_timeseries(
    site_id: Optional[str] = Query(None, description="Site name or UUID; omit for all"),
    start_date: date = Query(..., description="Start of range"),
    end_date: date = Query(..., description="End of range"),
    bucket: str = Query("hour", description="Time bucket: hour or day"),
):
    """
    Time-series of fault flag values (for React/Grafana-style charts).
    Returns one row per (time_bucket, fault_id) with SUM(flag_value).
    Join to fault_definitions for display names; here we return fault_id as metric.
    """
    if bucket not in ("hour", "day"):
        bucket = "hour"
    conditions = ["ts::date >= %s", "ts::date <= %s"]
    params: list = [start_date, end_date]
    if site_id:
        if resolve_site_uuid(site_id, create_if_empty=False) is None:
            raise HTTPException(404, f"No site found for: {site_id!r}")
        conditions.append("(fr.site_id = %s OR fr.site_id IN (SELECT name FROM sites WHERE id::text = %s))")
        params.extend([site_id, site_id])

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT date_trunc(%s, fr.ts) AS time, fr.fault_id AS metric, SUM(fr.flag_value)::float AS value
                FROM fault_results fr
                WHERE {" AND ".join(conditions)}
                GROUP BY 1, fr.fault_id
                ORDER BY 1, fr.fault_id
                """,
                [bucket, *params],
            )
            rows = cur.fetchall()

    def _ts_iso_utc(dt):
        """Format datetime as ISO UTC with Z so frontend parses as UTC and displays in local time (DST-safe)."""
        if dt is None:
            return None
        if getattr(dt, "tzinfo", None) is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"

    return {
        "site_id": site_id,
        "period": {"start": str(start_date), "end": str(end_date)},
        "bucket": bucket,
        "series": [
            {"time": _ts_iso_utc(r["time"]), "metric": r["metric"], "value": float(r["value"])}
            for r in rows
        ],
    }


@router.get("/faults-by-equipment", summary="Fault count per device (for bar chart)")
def get_faults_by_equipment(
    site_id: Optional[str] = Query(None, description="Site name or UUID; omit for all"),
    start_date: date = Query(..., description="Start of range"),
    end_date: date = Query(..., description="End of range"),
):
    """
    Per-equipment count of distinct faults active in the period (flag_value=1).
    Includes equipment name and BACnet device ID when points have one.
    For bar chart: which device had how many active faults in the range.
    """
    conditions = [
        "fr.ts::date >= %s",
        "fr.ts::date <= %s",
        "fr.flag_value = 1",
    ]
    params: list = [start_date, end_date]
    if site_id:
        if resolve_site_uuid(site_id, create_if_empty=False) is None:
            raise HTTPException(404, f"No site found for: {site_id!r}")
        conditions.append(
            "(fr.site_id = %s OR fr.site_id IN (SELECT name FROM sites WHERE id::text = %s))"
        )
        params.extend([site_id, site_id])

    with get_conn() as conn:
        with conn.cursor() as cur:
            # Aggregate by (site_id, equipment_id) from fault_results; resolve to equipment id/name and bacnet
            cur.execute(
                f"""
                WITH active AS (
                    SELECT fr.site_id, fr.equipment_id,
                           COUNT(DISTINCT fr.fault_id) AS active_fault_count
                    FROM fault_results fr
                    WHERE {" AND ".join(conditions)}
                    GROUP BY fr.site_id, fr.equipment_id
                )
                SELECT a.site_id, a.equipment_id AS equipment_id_text, a.active_fault_count,
                       e.id AS equipment_uuid, e.name AS equipment_name,
                       (SELECT p.bacnet_device_id FROM points p
                        WHERE p.equipment_id = e.id AND p.bacnet_device_id IS NOT NULL
                        LIMIT 1) AS bacnet_device_id
                FROM active a
                LEFT JOIN sites s ON (s.name = a.site_id OR s.id::text = a.site_id)
                LEFT JOIN equipment e ON e.site_id = s.id
                    AND (e.name = a.equipment_id OR e.id::text = a.equipment_id)
                ORDER BY a.active_fault_count DESC, a.equipment_id
                """,
                params,
            )
            rows = cur.fetchall()

    out = []
    for r in rows:
        out.append({
            "site_id": r["site_id"],
            "equipment_id": r["equipment_uuid"] if r["equipment_uuid"] else r["equipment_id_text"],
            "equipment_name": r["equipment_name"] or r["equipment_id_text"] or "—",
            "bacnet_device_id": r["bacnet_device_id"],
            "active_fault_count": int(r["active_fault_count"]),
        })
    return {
        "site_id": site_id,
        "period": {"start": str(start_date), "end": str(end_date)},
        "by_equipment": out,
    }


@router.get("/fault-results-series", summary="Distinct fault × site × equipment (for data preview selector)")
def get_fault_results_series(
    site_id: Optional[str] = Query(None, description="Site name or UUID; omit for all"),
    start_date: Optional[date] = Query(None, description="Start of range; omit for last 30 days"),
    end_date: Optional[date] = Query(None, description="End of range; omit for today"),
):
    """
    Returns distinct (fault_id, site_id, equipment_id) that have fault_results in the range.
    Used by the frontend to build the "which dataframe to view" selector (tabs/dropdown).
    """
    end = end_date or date.today()
    start = start_date or (end - timedelta(days=30))
    conditions = ["fr.ts::date >= %s", "fr.ts::date <= %s"]
    params: list = [start, end]
    if site_id:
        if resolve_site_uuid(site_id, create_if_empty=False) is None:
            raise HTTPException(404, f"No site found for: {site_id!r}")
        conditions.append(
            "(fr.site_id = %s OR fr.site_id IN (SELECT name FROM sites WHERE id::text = %s))"
        )
        params.extend([site_id, site_id])

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT DISTINCT fr.fault_id, fr.site_id, fr.equipment_id
                FROM fault_results fr
                WHERE {" AND ".join(conditions)}
                ORDER BY fr.fault_id, fr.site_id, fr.equipment_id
                """,
                params,
            )
            rows = cur.fetchall()
            # Resolve equipment names for labels
            out = []
            for r in rows:
                cur.execute(
                    """
                    SELECT e.name AS equipment_name
                    FROM sites s
                    LEFT JOIN equipment e ON e.site_id = s.id
                        AND (e.name = %s OR e.id::text = %s)
                    WHERE s.name = %s OR s.id::text = %s
                    LIMIT 1
                    """,
                    (r["equipment_id"], r["equipment_id"], r["site_id"], r["site_id"]),
                )
                eq = cur.fetchone()
                equipment_name = (eq and eq["equipment_name"]) or r["equipment_id"] or "—"
                out.append({
                    "fault_id": r["fault_id"],
                    "site_id": r["site_id"],
                    "equipment_id": r["equipment_id"],
                    "label": f"{r['fault_id']} — {equipment_name}",
                })
    return {"series": out, "period": {"start": str(start), "end": str(end)}}


def _ts_iso_utc(dt) -> str:
    if hasattr(dt, "isoformat"):
        if getattr(dt, "tzinfo", None) is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.isoformat().replace("+00:00", "Z")
    return str(dt)


@router.get("/fault-results-raw", summary="Last N rows of fault_results (for data preview grid)")
def get_fault_results_raw(
    fault_id: str = Query(..., description="Fault ID (e.g. from YAML)"),
    site_id: Optional[str] = Query(None, description="Site name or UUID; omit for all"),
    equipment_id: Optional[str] = Query(None, description="Equipment id/name; omit for all"),
    limit: int = Query(50, ge=1, le=500, description="Number of rows (most recent)"),
):
    """
    Returns the last N rows from fault_results for the given fault_id (and optional site/equipment).
    For Excel-style data preview: timestamp, site_id, equipment_id, fault_id, flag_value, evidence.
    """
    conditions = ["fr.fault_id = %s"]
    params: list = [fault_id]
    if site_id:
        conditions.append(
            "(fr.site_id = %s OR fr.site_id IN (SELECT name FROM sites WHERE id::text = %s))"
        )
        params.extend([site_id, site_id])
    if equipment_id:
        conditions.append("fr.equipment_id = %s")
        params.append(equipment_id)
    params.append(limit)

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT ts, site_id, equipment_id, fault_id, flag_value, evidence
                FROM fault_results fr
                WHERE {" AND ".join(conditions)}
                ORDER BY ts DESC
                LIMIT %s
                """,
                params,
            )
            rows = cur.fetchall()

    # Most recent first in DB; for spreadsheet show chronological (oldest first)
    rows = list(reversed(rows))
    return {
        "rows": [
            {
                "ts": _ts_iso_utc(r["ts"]),
                "site_id": r["site_id"],
                "equipment_id": r["equipment_id"],
                "fault_id": r["fault_id"],
                "flag_value": int(r["flag_value"]),
                "evidence": r["evidence"],
            }
            for r in rows
        ],
        "count": len(rows),
    }


# --- System resources (host_metrics, container_metrics, disk_metrics from stack-host-stats) ---


def _table_exists(table: str) -> bool:
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT 1 FROM timescaledb_information.hypertables WHERE hypertable_name = %s",
                    (table,),
                )
                return cur.fetchone() is not None
    except Exception:
        return False


@router.get("/system/host", summary="Latest host metrics (memory, load, swap)")
def get_system_host():
    """Latest row per host from host_metrics. Empty if table missing or host-stats not running."""
    if not _table_exists("host_metrics"):
        return {"hosts": []}
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT DISTINCT ON (hostname) hostname, ts,
                  mem_total_bytes, mem_used_bytes, mem_available_bytes,
                  swap_total_bytes, swap_used_bytes, load_1, load_5, load_15
                FROM host_metrics ORDER BY hostname, ts DESC
                """
            )
            rows = cur.fetchall()
    return {
        "hosts": [
            {
                "hostname": r["hostname"],
                "ts": r["ts"].isoformat() if hasattr(r["ts"], "isoformat") else str(r["ts"]),
                "mem_used_gb": round(r["mem_used_bytes"] / (1024**3), 2),
                "mem_available_gb": round(r["mem_available_bytes"] / (1024**3), 2),
                "mem_total_gb": round(r["mem_total_bytes"] / (1024**3), 2),
                "swap_used_gb": round(r["swap_used_bytes"] / (1024**3), 2),
                "load_1": round(r["load_1"], 2),
                "load_5": round(r["load_5"], 2),
                "load_15": round(r["load_15"], 2),
            }
            for r in rows
        ]
    }


@router.get("/system/host/series", summary="Host metrics time series for charts")
def get_system_host_series(
    from_ts: str = Query(..., description="ISO datetime"),
    to_ts: str = Query(..., description="ISO datetime"),
):
    """Time series of host memory (used/available) and load. For React system resources charts."""
    if not _table_exists("host_metrics"):
        return {"series": []}
    try:
        from_dt = datetime.fromisoformat(from_ts.replace("Z", "+00:00"))
        to_dt = datetime.fromisoformat(to_ts.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        raise HTTPException(400, "Invalid from_ts or to_ts")
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT ts, hostname,
                  (mem_used_bytes / 1024.0 / 1024 / 1024) AS mem_used_gb,
                  (mem_available_bytes / 1024.0 / 1024 / 1024) AS mem_available_gb,
                  load_1, load_5, load_15,
                  (swap_used_bytes / 1024.0 / 1024 / 1024) AS swap_used_gb
                FROM host_metrics
                WHERE ts >= %s AND ts <= %s
                ORDER BY ts
                """,
                (from_dt, to_dt),
            )
            rows = cur.fetchall()
    # Pivot to series format: [{ time, metric, value }, ...]
    series = []
    for r in rows:
        t = r["ts"].isoformat() if hasattr(r["ts"], "isoformat") else str(r["ts"])
        host = r["hostname"] or "host"
        series.append({"time": t, "metric": "mem_used_gb", "value": float(r["mem_used_gb"]), "hostname": host})
        series.append({"time": t, "metric": "mem_available_gb", "value": float(r["mem_available_gb"]), "hostname": host})
        series.append({"time": t, "metric": "load_1", "value": float(r["load_1"]), "hostname": host})
        series.append({"time": t, "metric": "load_5", "value": float(r["load_5"]), "hostname": host})
        series.append({"time": t, "metric": "load_15", "value": float(r["load_15"]), "hostname": host})
        series.append({"time": t, "metric": "swap_used_gb", "value": float(r["swap_used_gb"]), "hostname": host})
    return {"series": series}


@router.get("/system/containers", summary="Latest container metrics (table)")
def get_system_containers():
    """Latest row per container from container_metrics. For React system resources table."""
    if not _table_exists("container_metrics"):
        return {"containers": []}
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT DISTINCT ON (container_name) container_name, ts,
                  cpu_pct, mem_usage_bytes, mem_limit_bytes, mem_pct, pids
                FROM container_metrics ORDER BY container_name, ts DESC
                """
            )
            rows = cur.fetchall()
    return {
        "containers": [
            {
                "container_name": r["container_name"],
                "ts": r["ts"].isoformat() if hasattr(r["ts"], "isoformat") else str(r["ts"]),
                "cpu_pct": round(r["cpu_pct"], 1),
                "mem_mb": round(r["mem_usage_bytes"] / (1024 * 1024), 1),
                "mem_pct": round(r["mem_pct"], 1) if r.get("mem_pct") is not None else None,
                "pids": r["pids"],
            }
            for r in rows
        ]
    }


@router.get("/system/containers/series", summary="Container metrics time series for charts")
def get_system_containers_series(
    from_ts: str = Query(..., description="ISO datetime"),
    to_ts: str = Query(..., description="ISO datetime"),
):
    """Time series of container memory (MB) and CPU %. For React charts."""
    if not _table_exists("container_metrics"):
        return {"series": []}
    try:
        from_dt = datetime.fromisoformat(from_ts.replace("Z", "+00:00"))
        to_dt = datetime.fromisoformat(to_ts.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        raise HTTPException(400, "Invalid from_ts or to_ts")
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT ts, container_name,
                  (mem_usage_bytes / 1024.0 / 1024) AS mem_mb,
                  cpu_pct
                FROM container_metrics
                WHERE ts >= %s AND ts <= %s
                ORDER BY ts, container_name
                """,
                (from_dt, to_dt),
            )
            rows = cur.fetchall()
    series = []
    for r in rows:
        t = r["ts"].isoformat() if hasattr(r["ts"], "isoformat") else str(r["ts"])
        series.append({"time": t, "metric": r["container_name"], "value": float(r["mem_mb"]), "type": "mem_mb"})
        series.append({"time": t, "metric": r["container_name"], "value": float(r["cpu_pct"]), "type": "cpu_pct"})
    return {"series": series}


@router.get("/system/disk", summary="Latest disk usage per mount")
def get_system_disk():
    """Latest disk_metrics per host/mount. For React system resources (hard drive space)."""
    if not _table_exists("disk_metrics"):
        return {"disks": []}
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT DISTINCT ON (hostname, mount_path) hostname, mount_path, ts,
                  total_bytes, used_bytes, free_bytes
                FROM disk_metrics ORDER BY hostname, mount_path, ts DESC
                """
            )
            rows = cur.fetchall()
    return {
        "disks": [
            {
                "hostname": r["hostname"],
                "mount_path": r["mount_path"],
                "ts": r["ts"].isoformat() if hasattr(r["ts"], "isoformat") else str(r["ts"]),
                "used_gb": round(r["used_bytes"] / (1024**3), 2),
                "free_gb": round(r["free_bytes"] / (1024**3), 2),
                "total_gb": round(r["total_bytes"] / (1024**3), 2),
                "used_pct": round(100.0 * r["used_bytes"] / r["total_bytes"], 1) if r["total_bytes"] else 0,
            }
            for r in rows
        ]
    }
