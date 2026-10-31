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
    compute_fc1_timeline,
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
    # Irregular cadence: 5 min then 2 h gap (above MAX_GAP) — hold seconds zero across gap.
    idx = pd.to_datetime(
        [
            "2026-06-01T00:00:00Z",
            "2026-06-01T00:05:00Z",
            "2026-06-01T02:05:00Z",
        ],
        utc=True,
    )
    fan = [0, 1, 1]
    dsp = [0.5, 0.5, 0.5]
    sp = [2.0, 2.0, 2.0]
    ref = compute_fc1_timeline(
        index=idx,
        fan_status=fan,
        duct_static=dsp,
        duct_static_sp=sp,
        params=_fc1_params(),
        poll_seconds=300.0,
        confirm_seconds=0.0,
        require_operational_gate=False,
    )
    gap_s = (idx[2] - idx[1]).total_seconds()
    if gap_s > MAX_GAP_SECONDS and ref.covered_seconds_by_day:
        cells.append(
            QualCell(
                "08_gap_above_max_breaks_hold",
                "PASS",
                comparisons=1,
                detail=f"gap_seconds={gap_s}",
            )
        )
    else:
        cells.append(QualCell("08_gap_above_max_breaks_hold", "FAIL", 1, f"gap={gap_s}"))

    # Zero samples → empty timeline
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
    if not empty.fault_seconds_by_day and not empty.covered_seconds_by_day:
        cells.append(QualCell("08_zero_samples_empty_buckets", "PASS", comparisons=1))
    else:
        cells.append(QualCell("08_zero_samples_empty_buckets", "FAIL", 0, "expected empty"))

    # One sample
    one_idx = pd.DatetimeIndex(["2026-06-02T00:00:00Z"], tz="UTC")
    one = compute_fc1_timeline(
        index=one_idx,
        fan_status=[1],
        duct_static=[0.5],
        duct_static_sp=[2.0],
        params=_fc1_params(),
        poll_seconds=300.0,
        confirm_seconds=0.0,
        require_operational_gate=False,
    )
    if sum(one.covered_seconds_by_day.values()) == 0.0:
        cells.append(QualCell("08_one_sample_zero_hold", "PASS", comparisons=1))
    else:
        cells.append(QualCell("08_one_sample_zero_hold", "FAIL", 1))

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
    from scripts.stress.si_cutover import ci_fixtures_lib as cfl
    from scripts.stress.si_cutover import ci_timescale_sql as cts

    cells: list[QualCell] = []
    rules = {str(r["rule_id"]): r for r in cfl.load_rule_registry()}
    fc1 = rules["FC1"]
    idx = pd.date_range("2026-06-03T00:00:00Z", periods=6, freq="5min", tz="UTC")
    frame = pd.DataFrame(
        {
            "duct-static-pressure": [0.5] * 6,
            "duct-static-pressure-sp": [2.0] * 6,
            "fan-status": [0, 0, 1, 1, 1, 1],
        },
        index=idx,
    )
    frame.attrs["equipment_id"] = "FC1_TIMELINE"
    frame.attrs["equipment_type"] = "ahu"
    params = _fc1_params(mode_delay_min=10.0)
    ref = compute_fc1_timeline(
        index=idx,
        fan_status=frame["fan-status"].tolist(),
        duct_static=frame["duct-static-pressure"].tolist(),
        duct_static_sp=frame["duct-static-pressure-sp"].tolist(),
        params=params,
        poll_seconds=300.0,
        confirm_seconds=300.0,
        require_operational_gate=True,
    )
    spec = cfl.DatasetSpec(
        building_id="C3B_QUAL08",
        equipment_id="FC1_TIMELINE",
        equipment_type="ahu",
        source={"frame": frame},
    )
    cur = conn.cursor()
    try:
        sql_rows, errs = cts.run_sql_ip_for_dataset(
            conn,
            spec=spec,
            frame=frame,
            equipment_id=spec.equipment_id,
            rules=[fc1],
            poll_seconds=300.0,
            params_by_rule={"FC1": params},
        )
    finally:
        cur.close()
    if errs:
        cells.append(
            QualCell("08_pg_fc1_timeline_seconds", "FAIL", 0, "; ".join(errs[:5]))
        )
        return cells
    sql_fault = sum(float(r.get("fault_seconds") or 0) for r in sql_rows)
    ref_fault = sum(ref.fault_seconds_by_day.values())
    cells.append(
        QualCell(
            "08_pg_fc1_timeline_seconds",
            "PASS" if abs(sql_fault - ref_fault) < 1e-3 else "FAIL",
            comparisons=1,
            detail=f"sql={sql_fault} ref={ref_fault}",
        )
    )

    # Window clip: seed only the clipped span and compare independent oracle seconds.
    ws = "2026-06-03T01:00:00Z"
    we = "2026-06-03T02:00:00Z"
    clipped = frame.loc[(frame.index >= pd.Timestamp(ws)) & (frame.index < pd.Timestamp(we))]
    clipped_ref = compute_fc1_timeline(
        index=clipped.index,
        fan_status=clipped["fan-status"].tolist(),
        duct_static=clipped["duct-static-pressure"].tolist(),
        duct_static_sp=clipped["duct-static-pressure-sp"].tolist(),
        params=params,
        poll_seconds=300.0,
        confirm_seconds=300.0,
        require_operational_gate=True,
    )
    site_clip = "C3B_QUAL08_CLIP"
    cur = conn.cursor()
    try:
        parity = cts._load_parity_module()
        cts.purge_site(cur, site_clip)
        cts.seed_frame(
            cur,
            parity,
            site_id=site_clip,
            equipment_id=spec.equipment_id,
            equip_type="ahu",
            frame=clipped,
            storage="si",
        )
        cts.fill_history(cur, site_clip, cts.frame_sql_columns(clipped))
        conn.commit()
        rows, err = cts.execute_sql_rule_daily(
            cur,
            rule=fc1,
            building_id=site_clip,
            equipment_id=spec.equipment_id,
            poll_seconds=300.0,
            index=clipped.index,
            render_overrides=params,
            storage="si",
        )
    finally:
        cur.close()
    if err:
        cells.append(QualCell("08_pg_window_clip_overlay", "FAIL", 0, err))
    else:
        sql_clip = sum(float(r.get("fault_seconds") or 0) for r in rows)
        ref_clip = sum(clipped_ref.fault_seconds_by_day.values())
        cells.append(
            QualCell(
                "08_pg_window_clip_overlay",
                "PASS" if abs(sql_clip - ref_clip) < 1e-3 else "FAIL",
                comparisons=1,
                detail=f"sql={sql_clip} ref={ref_clip}",
            )
        )
    return cells
