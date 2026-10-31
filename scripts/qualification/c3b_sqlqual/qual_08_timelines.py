"""SQL-QUAL-08 — cadence, gaps, window clip, sample-count edge cases."""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parents[3]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from scripts.qualification.c3b_sqlqual.matrix import QualCell  # noqa: E402
from tests.qualification.fc1_mode_delay_timeline_reference import (  # noqa: E402
    MAX_GAP_SECONDS,
    build_synthetic_fc1_frame,
    compute_fc1_timeline,
    grid_params,
)


def _fc1_params(mode_delay_min: float = 0.0) -> dict[str, float]:
    return {
        "eps_vfd_spd": 0.13,
        "eps_dsp": 29.8608,
        "mode_delay_min": mode_delay_min,
        "startup_delay_min": 0.0,
    }


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
    fan = [0, 1, 1]
    ref = compute_fc1_timeline(
        index=idx,
        fan_status=fan,
        duct_static=[0.5, 0.5, 0.5],
        duct_static_sp=[2.0, 2.0, 2.0],
        params=_fc1_params(),
        poll_seconds=300.0,
        confirm_seconds=0.0,
        require_operational_gate=False,
    )
    gap_s = (idx[2] - idx[1]).total_seconds()
    if gap_s > MAX_GAP_SECONDS and ref.covered_seconds_by_day:
        cells.append(QualCell("08_gap_above_max_breaks_hold", "PASS", comparisons=1))
    else:
        cells.append(QualCell("08_gap_above_max_breaks_hold", "FAIL", 1, f"gap={gap_s}"))

    empty = compute_fc1_timeline(
        index=pd.DatetimeIndex([], tz="UTC"),
        fan_status=[],
        duct_static=[],
        duct_static_sp=[],
        params=_fc1_params(),
        poll_seconds=300.0,
        confirm_seconds=0.0,
        require_operational_gate=False,
    )
    if not empty.fault_seconds_by_day:
        cells.append(QualCell("08_zero_samples_empty_buckets", "PASS", comparisons=1))
    else:
        cells.append(QualCell("08_zero_samples_empty_buckets", "FAIL", 0))

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
    from scripts.stress.si_cutover import ci_fixtures_lib as cfl
    from scripts.stress.si_cutover import ci_timescale_sql as cts

    cells: list[QualCell] = []
    rules = {str(r["rule_id"]): r for r in cfl.load_rule_registry()}
    fc1 = rules["FC1"]
    frame = build_synthetic_fc1_frame(poll_seconds=300.0, n_samples=36)
    frame.attrs["equipment_type"] = "ahu"
    case = {"mode_delay_min": 10.0, "startup_delay_min": 0.0, "poll_seconds": 300.0}
    params = grid_params(case)
    spec = cfl.DatasetSpec(
        building_id="C3B_QUAL08",
        equipment_id=str(frame.attrs.get("equipment_id") or "AHU_CASE_FC1"),
        equipment_type="ahu",
        source={"frame": frame},
    )
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
    res = run_rule(
        "FC1",
        frame,
        params=params,
        poll_seconds=300.0,
        require_operational_gates=True,
    )
    fault_by_day, _ = daily_fault_and_covered_seconds(
        res.confirmed_fault, frame.index, poll_seconds=300.0
    )
    pandas_fault = sum(fault_by_day.values())
    ref_fault = sum(ref.fault_seconds_by_day.values())
    sql_rows, errs = cts.run_sql_ip_for_dataset(
        conn,
        spec=spec,
        frame=frame,
        equipment_id=spec.equipment_id,
        rules=[fc1],
        poll_seconds=300.0,
        params_by_rule={"FC1": params},
    )
    conn.commit()
    if errs:
        cells.append(QualCell("08_pg_fc1_timeline_seconds", "FAIL", 0, "; ".join(errs[:5])))
        return cells
    sql_fault = sum(float(r.get("fault_seconds") or 0) for r in sql_rows)
    ok = abs(sql_fault - pandas_fault) < 1e-3 and abs(sql_fault - ref_fault) < 1e-3
    cells.append(
        QualCell(
            "08_pg_fc1_timeline_seconds",
            "PASS" if ok else "FAIL",
            comparisons=2,
            detail=f"sql={sql_fault} pandas={pandas_fault} ref={ref_fault}",
        )
    )
    return cells
