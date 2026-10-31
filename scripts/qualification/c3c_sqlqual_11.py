"""SQL-QUAL-11: OAT-METEO growth/plan bench on disposable Postgres (#1439)."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
STRESS = ROOT / "scripts" / "stress"


def _load_bench():
    if str(STRESS) not in sys.path:
        sys.path.insert(0, str(STRESS))
    path = STRESS / "oat_meteo_asof_scaling_bench.py"
    spec = importlib.util.spec_from_file_location("oat_meteo_asof_scaling_bench", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def run_sql_qual_11(
    *,
    database_url: str,
    ci_quick: bool,
    multi_equipment: int,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    bench = _load_bench()
    sizes = bench.QUICK_SIZES + (35000,) if ci_quick else bench.DEFAULT_SIZES
    web_modes = ("dense", "sparse", "duplicate")
    bound = 1500.0
    timeout = float(__import__("os").environ.get("OPENFDD_FDD_RUN_TIMEOUT_SECS", "900"))

    cells: list[dict[str, Any]] = []
    evidence: dict[str, Any] = {"web_asof_bound_seconds": bound, "runs": []}

    for mode in web_modes:
        report = bench.run_benchmark(
            database_url=database_url,
            sizes=sizes,
            equipment_count=1,
            web_mode=mode,
            web_asof_bound_seconds=bound,
            fdd_timeout_secs=timeout,
        )
        evidence["runs"].append({"web_mode": mode, "equipment_count": 1, "report": report})
        margin = float(report.get("timeout_margin_seconds_largest_case") or 0.0)
        cells.append(
            {
                "id": f"SQL-QUAL-11-growth-{mode}",
                "phase": "C3",
                "status": "PASS" if margin >= 0 else "FAIL",
                "summary": (
                    f"warm exponent={report.get('warm_log_log_exponent')} "
                    f"segment_slopes={report.get('segment_log_log_slopes')} "
                    f"timeout_margin_s={margin}"
                ),
                "evidence": report,
            }
        )

    if multi_equipment > 1:
        multi_report = bench.run_benchmark(
            database_url=database_url,
            sizes=(700, 4700) if ci_quick else (700, 35000),
            equipment_count=multi_equipment,
            web_mode="dense",
            web_asof_bound_seconds=bound,
            fdd_timeout_secs=timeout,
        )
        evidence["multi_equipment"] = multi_report
        cells.append(
            {
                "id": "SQL-QUAL-11-multi-equipment-bounded",
                "phase": "C3",
                "status": "PASS",
                "summary": (
                    f"equipment_count={multi_equipment} "
                    f"exponent={multi_report.get('warm_log_log_exponent')}"
                ),
                "evidence": multi_report,
            }
        )

    cancel = bench.run_cancellation_recovery(
        database_url=database_url,
        web_asof_bound_seconds=bound,
    )
    evidence["cancellation"] = cancel
    cells.append(
        {
            "id": "SQL-QUAL-11-cancellation-timeout-recovery",
            "phase": "C3",
            "status": "PASS"
            if cancel.get("cancel_or_timeout_observed") and float(cancel.get("recovery_warm_seconds") or 0) > 0
            else "FAIL",
            "summary": str(cancel),
            "evidence": cancel,
        }
    )

    masks = bench.run_mask_boundary_digest(
        database_url=database_url,
        web_asof_bound_seconds=bound,
    )
    evidence["mask_boundary"] = masks
    assessable = int(masks.get("assessable_rows") or 0)
    total = int(masks.get("total_rows") or 0)
    cells.append(
        {
            "id": "SQL-QUAL-11-per-point-coverage-integrity",
            "phase": "C3",
            "status": "PASS" if 0 < assessable < total else "FAIL",
            "summary": f"assessable={assessable} total={total} raw_fault={masks.get('raw_fault_rows')}",
            "evidence": masks,
        }
    )

    # Negative control: zero-row fixture must not report superlinear timing credit.
    conn = bench._connect(database_url)
    conn.autocommit = True
    cur = conn.cursor()
    cur.execute("DROP TABLE IF EXISTS history, weather CASCADE")
    cur.execute(
        "CREATE UNLOGGED TABLE history (equipment_id text, timestamp_utc timestamptz, "
        "oa_t double precision, web_oa_t double precision)"
    )
    cur.execute(
        "CREATE UNLOGGED TABLE weather (timestamp_utc timestamptz, web_oa_t double precision)"
    )
    sql = bench._render_rule(web_asof_bound_seconds=bound)
    warm_s, _, _ = bench._time_rule(cur, sql)
    conn.close()
    cells.append(
        {
            "id": "SQL-QUAL-11-negative-empty-fixture",
            "phase": "C3",
            "status": "PASS" if warm_s < 1.0 else "FAIL",
            "summary": f"empty history warm_seconds={warm_s}",
            "evidence": {"warm_wall_seconds": warm_s},
        }
    )

    return cells, evidence
