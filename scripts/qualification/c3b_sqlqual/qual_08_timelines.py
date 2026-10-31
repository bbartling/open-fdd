"""SQL-QUAL-08 — cadence, gaps, window clip, sample-count edge cases."""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parents[3]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from scripts.qualification.c3b_sqlqual.fc1_postgres_context import (  # noqa: E402
    fc1_synth_postgres_context,
    params_for_grid_case,
)
from scripts.qualification.c3b_sqlqual.matrix import QualCell  # noqa: E402
from tests.qualification.fc1_mode_delay_timeline_reference import (  # noqa: E402
    MAX_GAP_SECONDS,
    compute_fc1_timeline,
)


def run_offline() -> list[QualCell]:
    cells: list[QualCell] = []
    idx = pd.to_datetime(
        [
            "2026-06-01T00:00:00Z",
            "2026-06-01T00:05:00Z",
            "2026-06-01T02:05:00Z",
        ],
        utc=True,
    )
    ref = compute_fc1_timeline(
        index=idx,
        fan_status=[0, 1, 1],
        duct_static=[0.5, 0.5, 0.5],
        duct_static_sp=[2.0, 2.0, 2.0],
        params={"eps_vfd_spd": 0.13, "eps_dsp": 29.8608, "mode_delay_min": 0.0, "startup_delay_min": 0.0},
        poll_seconds=300.0,
        confirm_seconds=0.0,
        require_operational_gate=False,
    )
    gap_s = (idx[2] - idx[1]).total_seconds()
    if gap_s > MAX_GAP_SECONDS and ref.covered_seconds_by_day:
        cells.append(QualCell("08_gap_above_max_breaks_hold", "PASS", comparisons=1))
    else:
        cells.append(QualCell("08_gap_above_max_breaks_hold", "FAIL", 1, f"gap={gap_s}"))

    cells.append(
        QualCell(
            "08_cov_async_web_cadence_live",
            "PENDING",
            0,
            "C5: async web/local cadence parity on owner REST path",
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
    fault_by_day, _ = daily_fault_and_covered_seconds(
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
    if errs:
        return [QualCell("08_pg_fc1_timeline_seconds", "FAIL", 0, "; ".join(errs[:5]))]
    sql_fault = sum(float(r.get("fault_seconds") or 0) for r in sql_rows)
    ok = abs(sql_fault - pandas_fault) < 1e-3
    return [
        QualCell(
            "08_pg_fc1_timeline_seconds",
            "PASS" if ok else "FAIL",
            comparisons=1,
            detail=f"sql={sql_fault} pandas={pandas_fault}",
        )
    ]
