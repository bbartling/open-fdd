"""
Minimal continuous FDD loop.

Reads timeseries from DB → runs rules → writes fault_results to TimescaleDB.
Designed for Grafana; orchestration/alerts layer on later.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import pandas as pd
from psycopg2.extras import execute_values

from open_fdd.platform.config import get_platform_settings
from open_fdd.platform.database import get_conn
from open_fdd.schema import FDDResult, results_from_runner_output


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
    site_id: str = "default",
    rules_dir: Optional[Path] = None,
    brick_ttl: Optional[Path] = None,
    lookback_days: int = 3,
) -> list[FDDResult]:
    """
    Run FDD on last N days of data, write fault_results to DB.
    Returns list of FDDResult written.
    """
    from open_fdd.engine.brick_resolver import resolve_from_ttl, get_equipment_types_from_ttl
    from open_fdd.engine.runner import RuleRunner, load_rules_from_dir

    settings = get_platform_settings()
    rules_path = rules_dir or Path(settings.rules_yaml_dir)
    if not rules_path.exists():
        rules_path = Path(__file__).resolve().parent.parent.parent / "open_fdd" / "rules"

    ttl_path = brick_ttl or Path(settings.brick_ttl_dir)
    if isinstance(ttl_path, str):
        ttl_path = Path(ttl_path)

    column_map = resolve_from_ttl(str(ttl_path)) if ttl_path.exists() else {}
    equipment_types = get_equipment_types_from_ttl(str(ttl_path)) if ttl_path.exists() else []
    all_rules = load_rules_from_dir(rules_path)
    rules = [
        r for r in all_rules
        if not r.get("equipment_type") or any(et in equipment_types for et in r.get("equipment_type", []))
    ]
    runner = RuleRunner(rules=rules)

    end_ts = datetime.utcnow()
    start_ts = end_ts - timedelta(days=lookback_days)

    # Get equipment from DB; fallback to site_id as single "equipment" for MVP
    with get_conn() as conn:
        with conn.cursor() as cur:
            try:
                cur.execute(
                    "SELECT id, name FROM equipment WHERE site_id::text = %s",
                    (site_id,),
                )
                equipment_rows = cur.fetchall()
            except Exception:
                equipment_rows = [{"id": None, "name": site_id}]

    if not equipment_rows:
        equipment_rows = [{"id": None, "name": site_id}]

    all_results: list[FDDResult] = []
    for eq in equipment_rows:
        eq_id = eq["name"]
        df = load_timeseries_for_equipment(site_id, eq_id, start_ts, end_ts, column_map)
        if df is None or len(df) < 10:
            continue
        res = runner.run(
            df,
            timestamp_col="timestamp",
            rolling_window=settings.rolling_window,
            column_map=column_map,
            params={"units": "imperial"},
            skip_missing_columns=True,
        )
        results = results_from_runner_output(res, site_id, eq_id, timestamp_col="timestamp")
        all_results.extend(results)

    if all_results:
        _write_fault_results(all_results)

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
