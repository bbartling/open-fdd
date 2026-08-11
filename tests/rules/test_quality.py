"""Role-aware quality normalization."""

from __future__ import annotations

import pandas as pd

from open_fdd.quality import (
    REASON_NON_NUMERIC,
    REASON_OUT_OF_RANGE,
    REASON_SENTINEL,
    apply_normalized,
    assess_frame,
    normalize_role_series,
)
from open_fdd.rules import run_rule


def _idx(n=6):
    return pd.date_range("2026-01-01", periods=n, freq="5min", tz="UTC")


def test_sentinels_invalid_but_zero_status_is_valid():
    idx = _idx()
    zone = pd.Series([72.0, 999.0, 888.0, -999.0, 71.0, 70.0], index=idx)
    qz = normalize_role_series(zone, "zone-air-temp")
    assert qz.valid_sample_count == 3
    assert qz.reason_counts[REASON_SENTINEL] == 3
    assert qz.normalized.isna().sum() == 3

    status = pd.Series([0, 1, 0, 1, 0, 0], index=idx)
    qs = normalize_role_series(status, "fan-status")
    assert qs.valid_sample_count == 6
    assert qs.invalid_sample_count == 0


def test_command_zero_and_one_are_valid():
    idx = _idx()
    cmd = pd.Series([0.0, 1.0, 0.5, 100.0, 0.0, 25.0], index=idx)
    q = normalize_role_series(cmd, "fan-cmd")
    assert q.valid_sample_count == 6


def test_non_numeric_command_is_invalid():
    idx = _idx()
    cmd = pd.Series([0.0, "invalid", 1.0, 0.0, 1.0, 0.0], index=idx)
    q = normalize_role_series(cmd, "fan-cmd")
    assert q.reason_counts[REASON_NON_NUMERIC] == 1
    assert q.valid_sample_count == 5


def test_speed_feedback_out_of_range():
    idx = _idx()
    spd = pd.Series([0.0, 50.0, -5.0, 101.0, 1.0, 80.0], index=idx)
    q = normalize_role_series(spd, "fan-speed-feedback")
    assert q.reason_counts[REASON_OUT_OF_RANGE] == 2
    assert q.valid_sample_count == 4


def test_negative_flow_impossible():
    idx = _idx()
    flow = pd.Series([200.0, -5.0, 180.0, 0.0, 190.0, 210.0], index=idx)
    q = normalize_role_series(flow, "zone-airflow")
    assert q.invalid_sample_count == 1
    assert "IMPOSSIBLE_FOR_ROLE" in q.reason_counts


def test_frame_summary_and_rule_skips_all_sentinel_required():
    idx = _idx()
    df = pd.DataFrame(
        {
            "zone-air-temp": [999.0] * 6,
            "fan-status": [1, 1, 1, 1, 1, 1],
        },
        index=idx,
    )
    df.attrs["equipment_id"] = "VAV_1"
    df.attrs["equipment_type"] = "VAV"
    fq = assess_frame(df, ["zone-air-temp", "fan-status"])
    assert fq.roles["zone-air-temp"].valid_coverage == 0
    assert fq.roles["fan-status"].valid_coverage == 1
    result = run_rule("VAV-1", df, poll_seconds=300.0, require_operational_gates=False)
    assert result.status == "SKIPPED_MISSING_ROLES"


def test_apply_normalized_does_not_fragment():
    idx = _idx()
    df = pd.DataFrame(
        {f"zone-air-temp": [72.0] * 6, "fan-status": [1.0] * 6},
        index=idx,
    )
    for i in range(20):
        df[f"extra_{i}"] = float(i)
    fq = assess_frame(df)
    out = apply_normalized(df, fq)
    assert "raw:zone-air-temp" in out.columns
    assert out["quality:fan-status"].dtype == "int8"
    slim = apply_normalized(df, fq, attach_raw_and_flags=False)
    assert "raw:zone-air-temp" not in slim.columns
    assert list(slim.columns) == list(df.columns)


def test_occupied_strings_are_valid_status():
    idx = _idx()
    occ = pd.Series(["occupied", "unoccupied", "occupied", "unoccupied", "occupied", "unoccupied"], index=idx)
    q = normalize_role_series(occ, "occupied")
    assert q.valid_sample_count == 6
    assert REASON_NON_NUMERIC not in q.reason_counts
    df = pd.DataFrame({"occupied": occ, "fan-status": [1.0] * 6}, index=idx)
    df.attrs["equipment_id"] = "AHU_1"
    df.attrs["equipment_type"] = "AHU"
    result = run_rule("SCHED-1", df, params={"confirm_min": 0}, poll_seconds=300.0)
    assert result.status in {"FAULT", "PASS"}
    assert result.status != "SKIPPED_MISSING_ROLES"
