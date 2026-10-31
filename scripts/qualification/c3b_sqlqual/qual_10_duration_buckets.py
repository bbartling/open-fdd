"""SQL-QUAL-10 — aggregate SQL, series overlay, independent oracle bucket agreement."""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parents[3]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from scripts.qualification.c3b_sqlqual.matrix import QualCell  # noqa: E402
from tests.qualification.fc1_mode_delay_timeline_reference import (  # noqa: E402
    build_synthetic_fc1_frame,
    compute_fc1_timeline,
    grid_params,
)


def run_offline() -> list[QualCell]:
    cells: list[QualCell] = []
    frame = build_synthetic_fc1_frame(poll_seconds=300.0, n_samples=24)
    params = grid_params({"mode_delay_min": 10.0, "startup_delay_min": 0.0, "poll_seconds": 300.0})
    ref = compute_fc1_timeline(
        index=frame.index,
        fan_status=frame["fan-status"].tolist(),
        duct_static=frame["duct-static-pressure"].tolist(),
        duct_static_sp=frame["duct-static-pressure-sp"].tolist(),
        params=params,
        poll_seconds=300.0,
        confirm_seconds=300.0,
        require_operational_gate=False,
    )
    ref_total = sum(ref.fault_seconds_by_day.values())
    if ref_total > 0:
        cells.append(QualCell("10_independent_oracle_nonzero", "PASS", comparisons=1))
    else:
        cells.append(QualCell("10_independent_oracle_nonzero", "FAIL", 0, "expected faults"))
    cells.append(
        QualCell(
            "10_rest_session_cache_generation",
            "PENDING",
            0,
            "C5: REST/session tuner/cache-generation contracts on owner stack",
        )
    )
    return cells


def run_postgres(conn) -> list[QualCell]:
    from scripts.stress.si_cutover import ci_fixtures_lib as cfl
    from scripts.stress.si_cutover import ci_timescale_sql as cts

    cells: list[QualCell] = []
    rules = {str(r["rule_id"]): r for r in cfl.load_rule_registry()}
    fc1 = rules["FC1"]
    frame = build_synthetic_fc1_frame(poll_seconds=300.0, n_samples=24)
    params = grid_params({"mode_delay_min": 10.0, "startup_delay_min": 0.0, "poll_seconds": 300.0})
    ref = compute_fc1_timeline(
        index=frame.index,
        fan_status=frame["fan-status"].tolist(),
        duct_static=frame["duct-static-pressure"].tolist(),
        duct_static_sp=frame["duct-static-pressure-sp"].tolist(),
        params=params,
        poll_seconds=300.0,
        confirm_seconds=300.0,
        require_operational_gate=False,
    )
    ref_total = sum(ref.fault_seconds_by_day.values())
    site = "C3B_QUAL10"
    equip = str(frame.attrs.get("equipment_id") or "AHU_CASE_FC1")
    cur = conn.cursor()
    try:
        parity = cts._load_parity_module()
        cts.purge_site(cur, site)
        cts.seed_frame(
            cur,
            parity,
            site_id=site,
            equipment_id=equip,
            equip_type="ahu",
            frame=frame,
            storage="si",
        )
        cts.fill_history(cur, site, cts.frame_sql_columns(frame))
        conn.commit()
        daily, err = cts.execute_sql_rule_daily(
            cur,
            rule=fc1,
            building_id=site,
            equipment_id=equip,
            poll_seconds=300.0,
            index=frame.index,
            render_overrides=params,
            storage="si",
        )
    finally:
        cur.close()
    if err:
        cells.append(QualCell("10_pg_aggregate_overlay_oracle", "FAIL", 0, err))
        return cells
    sql_total = sum(float(r.get("fault_seconds") or 0) for r in daily)
    ok = abs(sql_total - ref_total) < 1e-3
    cells.append(
        QualCell(
            "10_pg_aggregate_overlay_oracle",
            "PASS" if ok else "FAIL",
            comparisons=1,
            detail=f"sql={sql_total} oracle={ref_total}",
        )
    )
    covered = [r.get("covered_seconds") for r in daily if r.get("covered_seconds") is not None]
    if covered and all(float(c) > 0 for c in covered):
        cells.append(QualCell("10_pg_coverage_not_zero", "PASS", comparisons=len(covered)))
    else:
        cells.append(QualCell("10_pg_coverage_not_zero", "FAIL", 0, f"covered={covered}"))
    return cells
