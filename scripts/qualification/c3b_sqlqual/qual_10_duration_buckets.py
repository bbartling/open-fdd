"""SQL-QUAL-10 — aggregate SQL, series overlay, independent oracle bucket agreement."""

from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from scripts.qualification.c3b_sqlqual.fc1_postgres_context import (  # noqa: E402
    fc1_synth_postgres_context,
    params_for_grid_case,
)
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
        require_operational_gate=True,
    )
    if sum(ref.fault_seconds_by_day.values()) > 0:
        cells.append(QualCell("10_independent_oracle_nonzero", "PASS", comparisons=1))
    else:
        cells.append(QualCell("10_independent_oracle_nonzero", "FAIL", 0))
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
    from open_fdd.rules import run_rule
    from scripts.stress.si_cutover.capture_ip_baseline import daily_fault_and_covered_seconds
    from scripts.stress.si_cutover import ci_timescale_sql as cts

    fc1, spec, frame, params_ip, poll = fc1_synth_postgres_context()
    case = {"mode_delay_min": 10.0, "startup_delay_min": 0.0, "poll_seconds": poll}
    params = params_for_grid_case(params_ip, case)
    res = run_rule(
        "FC1",
        frame,
        params=params,
        poll_seconds=poll,
        require_operational_gates=True,
    )
    fault_by_day, covered_by_day = daily_fault_and_covered_seconds(
        res.confirmed_fault, frame.index, poll_seconds=poll
    )
    pandas_fault = sum(fault_by_day.values())
    sql_rows, errs = cts.run_sql_ip_for_dataset(
        conn,
        spec=spec,
        frame=frame,
        equipment_id=spec.equipment_id,
        rules=[fc1],
        poll_seconds=poll,
        params_by_rule={"FC1": params},
    )
    conn.commit()
    cells: list[QualCell] = []
    if errs:
        cells.append(QualCell("10_pg_aggregate_overlay_oracle", "FAIL", 0, "; ".join(errs[:5])))
        return cells
    sql_fault = sum(float(r.get("fault_seconds") or 0) for r in sql_rows)
    ok = abs(sql_fault - pandas_fault) < 1e-3
    cells.append(
        QualCell(
            "10_pg_aggregate_overlay_oracle",
            "PASS" if ok else "FAIL",
            comparisons=1,
            detail=f"sql={sql_fault} pandas={pandas_fault}",
        )
    )
    covered = [r.get("covered_seconds") for r in sql_rows if r.get("covered_seconds") is not None]
    if covered and all(float(c) > 0 for c in covered):
        cells.append(QualCell("10_pg_coverage_not_zero", "PASS", comparisons=len(covered)))
    else:
        cells.append(QualCell("10_pg_coverage_not_zero", "FAIL", 0, f"covered={covered}"))
    return cells
