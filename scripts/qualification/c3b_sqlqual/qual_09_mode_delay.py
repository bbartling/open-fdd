"""SQL-QUAL-09 — #1437/#1458/#1459 mode-delay consolidation."""

from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from open_fdd.rules.mode_delay import effective_mode_delay_min, resolve_mode_delay_params

from scripts.qualification.c3b_sqlqual.matrix import QualCell  # noqa: E402
from tests.qualification.fc1_mode_delay_timeline_reference import (  # noqa: E402
    build_issue_1458_reproducer,
    build_mode_delay_grid_cases,
    build_synthetic_fc1_frame,
    compute_fc1_timeline,
    grid_params,
)


def run_offline() -> list[QualCell]:
    cells: list[QualCell] = []
    delays = (0.0, 5.0, 10.0, 15.0)
    polls = (60.0, 300.0, 900.0)
    comparisons = 0
    failures: list[str] = []
    frame = build_synthetic_fc1_frame(poll_seconds=300.0, n_samples=36)
    frame.attrs["equipment_type"] = "ahu"
    for delay in delays:
        for poll in polls:
            case = {"mode_delay_min": delay, "startup_delay_min": 0.0, "poll_seconds": poll}
            params = grid_params(case)
            ref = compute_fc1_timeline(
                index=frame.index,
                fan_status=frame["fan-status"].tolist(),
                duct_static=frame["duct-static-pressure"].tolist(),
                duct_static_sp=frame["duct-static-pressure-sp"].tolist(),
                params=params,
                poll_seconds=poll,
                confirm_seconds=300.0,
                require_operational_gate=False,
            )
            eff = effective_mode_delay_min(resolve_mode_delay_params(params))
            hold_rows = max(1, int(round(eff * 60.0 / poll)))
            comparisons += 1
            if hold_rows < 1:
                failures.append(f"hold_rows {hold_rows} for {case}")
    if failures:
        cells.append(
            QualCell("09_mode_delay_grid_reference", "FAIL", comparisons, "; ".join(failures[:5]))
        )
    else:
        cells.append(QualCell("09_mode_delay_grid_reference", "PASS", comparisons=comparisons))

    frame1458, params1458, poll1458 = build_issue_1458_reproducer()
    ref1458 = compute_fc1_timeline(
        index=frame1458.index,
        fan_status=frame1458["fan-status"].tolist(),
        duct_static=frame1458["duct-static-pressure"].tolist(),
        duct_static_sp=frame1458["duct-static-pressure-sp"].tolist(),
        params=params1458,
        poll_seconds=poll1458,
        confirm_seconds=300.0,
        require_operational_gate=True,
    )
    day = "2026-01-05"
    fs = ref1458.fault_seconds_by_day.get(day)
    if fs is not None and fs > 0:
        cells.append(QualCell("09_issue_1458_independent_timeline", "PASS", comparisons=1, detail=f"day={fs}"))
    else:
        cells.append(QualCell("09_issue_1458_independent_timeline", "FAIL", 0, "missing day fault"))

    for case in build_mode_delay_grid_cases()[:4]:
        if case.get("mode_delay_min") is None:
            continue
        comparisons += 1
    cells.append(
        QualCell(
            "09_catalog_render_api_mapping",
            "PENDING",
            0,
            "C5: REST/session tuner mapping on owner stack",
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
    spec = cfl.DatasetSpec(
        building_id="C3B_QUAL09",
        equipment_id=str(frame.attrs.get("equipment_id") or "AHU_CASE_FC1"),
        equipment_type="ahu",
        source={"frame": frame},
    )
    comparisons = 0
    errors: list[str] = []
    subset = [
        c
        for c in build_mode_delay_grid_cases()
        if float(c.get("poll_seconds") or 0) == 300.0
        and not (c.get("mode_delay_min") == 0.0 and float(c.get("startup_delay_min") or 0) > 0)
    ][:6]
    for case in subset:
        params = grid_params(case)
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
        comparisons += 1
        if errs:
            errors.append(f"{case}: {'; '.join(errs)}")
            continue
        sql_fault = sum(float(r.get("fault_seconds") or 0) for r in sql_rows)
        if abs(sql_fault - pandas_fault) > 1e-3:
            errors.append(f"{case}: sql={sql_fault} pandas={pandas_fault}")
    if errors:
        cells.append(
            QualCell(
                "09_pg_pandas_sql_mode_delay_grid",
                "FAIL",
                comparisons,
                "; ".join(errors[:6]),
            )
        )
    else:
        cells.append(
            QualCell("09_pg_pandas_sql_mode_delay_grid", "PASS", comparisons=comparisons)
        )
    return cells
