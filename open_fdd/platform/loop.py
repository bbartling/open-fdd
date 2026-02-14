"""
Continuous FDD loop: periodic rule runs with hot-reload.

Every run (default every 3 hours): loads rules from YAML (analyst changes apply immediately),
pulls last N days of data into pandas, runs all rules, writes fault_results.
Analysts tune rules in YAML, spot-check in Grafana, no restart needed.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import pandas as pd
from psycopg2.extras import execute_values

from open_fdd.platform.config import get_platform_settings
from open_fdd.platform.database import get_conn
from open_fdd.platform.site_resolver import resolve_site_uuid
from open_fdd.schema import FDDResult, results_from_runner_output


def load_timeseries_for_site(
    site_id: str,
    start_ts: datetime,
    end_ts: datetime,
    column_map: dict[str, str],
) -> Optional[pd.DataFrame]:
    """
    Load all timeseries_readings for a site into a DataFrame (BACnet + weather).
    Columns = external_id; column_map applied for Brick resolution.
    """
    site_uuid = resolve_site_uuid(site_id, create_if_empty=False)
    if site_uuid is None:
        return None

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT p.id, p.external_id
                FROM points p
                WHERE p.site_id = %s
                ORDER BY p.external_id
                """,
                (str(site_uuid),),
            )
            rows = cur.fetchall()
    if not rows:
        return None

    point_ids = [r["id"] for r in rows]
    ext_ids = [r["external_id"] for r in rows]

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT tr.ts, p.external_id, tr.value
                FROM timeseries_readings tr
                JOIN points p ON tr.point_id = p.id
                WHERE tr.point_id = ANY(%s::uuid[])
                  AND tr.ts >= %s AND tr.ts <= %s
                ORDER BY tr.ts
                """,
                (point_ids, start_ts, end_ts),
            )
            rows = cur.fetchall()

    if not rows:
        return None

    df = pd.DataFrame(rows)
    df = df.pivot_table(index="ts", columns="external_id", values="value")
    df = df.reset_index()
    csv_cols = {ext: column_map.get(ext, ext) for ext in ext_ids}
    df = df.rename(columns=csv_cols)
    df["timestamp"] = pd.to_datetime(df["ts"])
    return df


def load_timeseries_for_equipment(
    site_id: str,
    equipment_id: str,
    start_ts: datetime,
    end_ts: datetime,
    column_map: dict[str, str],
) -> Optional[pd.DataFrame]:
    """
    Load timeseries_readings for one equipment into a DataFrame.
    Requires points.equipment_id and equipment table; falls back to site-level points.
    """
    import uuid

    try:
        site_uuid = uuid.UUID(site_id)
    except (ValueError, TypeError):
        site_uuid = site_id

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT p.id, p.external_id
                FROM points p
                LEFT JOIN equipment e ON p.equipment_id = e.id
                WHERE (p.site_id = %s OR p.site_id::text = %s)
                  AND (e.name = %s OR p.external_id IN ('sat','zt','fan_status'))
                """,
                (site_uuid, site_id, equipment_id),
            )
            rows = cur.fetchall()
    if not rows:
        return None

    point_ids = [r["id"] for r in rows]
    ext_ids = [r["external_id"] for r in rows]

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT tr.ts, p.external_id, tr.value
                FROM timeseries_readings tr
                JOIN points p ON tr.point_id = p.id
                WHERE tr.point_id = ANY(%s)
                  AND tr.ts >= %s AND tr.ts <= %s
                """,
                (point_ids, start_ts, end_ts),
            )
            rows = cur.fetchall()

    if not rows:
        return None

    df = pd.DataFrame(rows)
    df = df.pivot_table(index="ts", columns="external_id", values="value")
    df = df.reset_index()
    csv_cols = {ext: column_map.get(ext, ext) for ext in ext_ids}
    df = df.rename(columns=csv_cols)
    df["timestamp"] = pd.to_datetime(df["ts"])
    return df


def run_fdd_loop(
    site_id: Optional[str] = None,
    rules_dir: Optional[Path] = None,
    brick_ttl: Optional[Path] = None,
    lookback_days: Optional[int] = None,
) -> list[FDDResult]:
    """
    Run FDD on last N days of data, write fault_results to DB.
    Loads rules from YAML every run (analyst edits apply immediately).
    Runs all rules (sensor + weather) against site-level data.
    """
    from open_fdd.engine.brick_resolver import (
        resolve_from_ttl,
        get_equipment_types_from_ttl,
    )
    from open_fdd.engine.runner import RuleRunner, load_rules_from_dir

    settings = get_platform_settings()
    lookback = lookback_days if lookback_days is not None else settings.lookback_days

    # Rules: one place (analyst/rules); fallback to open_fdd/rules if missing
    repo_root = Path(__file__).resolve().parent.parent.parent
    if rules_dir is not None:
        rules_path = Path(rules_dir)
    else:
        rules_path = Path(settings.rules_dir)
        if not rules_path.is_absolute():
            rules_path = repo_root / rules_path
    if not rules_path.exists():
        rules_path = repo_root / "open_fdd" / "rules"

    ttl_path = brick_ttl or Path(
        getattr(settings, "brick_ttl_path", None) or settings.brick_ttl_dir
    )
    if isinstance(ttl_path, str):
        ttl_path = Path(ttl_path)
    if not ttl_path.is_absolute():
        ttl_path = repo_root / ttl_path

    column_map = resolve_from_ttl(str(ttl_path)) if ttl_path.exists() else {}
    equipment_types = (
        get_equipment_types_from_ttl(str(ttl_path)) if ttl_path.exists() else []
    )

    # Load rules every run (hot reload for analyst tuning)
    all_rules = load_rules_from_dir(rules_path)
    rules = [
        r
        for r in all_rules
        if not r.get("equipment_type")
        or any(et in equipment_types for et in r.get("equipment_type", []))
    ]
    runner = RuleRunner(rules=rules)

    end_ts = datetime.utcnow()
    start_ts = end_ts - timedelta(days=lookback)

    # Sites to run: one site or all
    with get_conn() as conn:
        with conn.cursor() as cur:
            if site_id:
                site_uuid = resolve_site_uuid(site_id, create_if_empty=False)
                if site_uuid is None:
                    return []
                cur.execute(
                    "SELECT id, name FROM sites WHERE id = %s",
                    (str(site_uuid),),
                )
            else:
                cur.execute("SELECT id, name FROM sites ORDER BY name")
            site_rows = cur.fetchall()

    all_results: list[FDDResult] = []
    sites_processed = 0
    try:
        for row in site_rows:
            sid = str(row["id"])
            site_name = row["name"] or sid
            df = load_timeseries_for_site(sid, start_ts, end_ts, column_map)
            if df is None or len(df) < 6:
                continue
            sites_processed += 1
            res = runner.run(
                df,
                timestamp_col="timestamp",
                rolling_window=getattr(settings, "rolling_window", None),
                column_map=column_map,
                params={"units": "imperial"},
                skip_missing_columns=True,
            )
            results = results_from_runner_output(
                res, site_name, site_name, timestamp_col="timestamp"
            )
            all_results.extend(results)

        if all_results:
            _write_fault_results(all_results)

        _write_fdd_run_log(
            run_ts=datetime.utcnow(),
            status="ok",
            sites_processed=sites_processed,
            faults_written=len(all_results),
        )
    except Exception as e:
        _write_fdd_run_log(
            run_ts=datetime.utcnow(),
            status="error",
            sites_processed=sites_processed,
            faults_written=0,
            error_message=str(e)[:500],
        )
        raise

    return all_results


def _write_fault_results(results: list[FDDResult]) -> None:
    """Bulk insert fault_results."""
    rows = [r.to_row() for r in results]
    with get_conn() as conn:
        with conn.cursor() as cur:
            execute_values(
                cur,
                """
                INSERT INTO fault_results (ts, site_id, equipment_id, fault_id, flag_value, evidence)
                VALUES %s
                """,
                rows,
                page_size=500,
            )
            conn.commit()


def _write_fdd_run_log(
    run_ts: datetime,
    status: str,
    sites_processed: int,
    faults_written: int,
    error_message: Optional[str] = None,
) -> None:
    """Record FDD run status for Grafana fault runner panel."""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO fdd_run_log (run_ts, status, sites_processed, faults_written, error_message)
                VALUES (%s, %s, %s, %s, %s)
                """,
                (run_ts, status, sites_processed, faults_written, error_message),
            )
            conn.commit()
