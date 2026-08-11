"""CHW-1 operational proof: skip / proven-off / proven-on."""

from __future__ import annotations

import pandas as pd

from open_fdd.rules import run_rule


def _frame(**cols) -> pd.DataFrame:
    n = len(next(iter(cols.values())))
    idx = pd.date_range("2026-01-01", periods=n, freq="5min", tz="UTC")
    df = pd.DataFrame(cols, index=idx)
    df.attrs["equipment_id"] = "CH_1"
    df.attrs["equipment_type"] = "CHILLER"
    return df


def _run(df, **kwargs):
    return run_rule(
        "CHW-1",
        df,
        params={"confirm_seconds": 0, "min_dt": 4.0, **kwargs.get("params", {})},
        poll_seconds=300.0,
        require_operational_gates=True,
    )


def test_no_proof_roles_skipped():
    df = _frame(
        **{
            "chilled-water-supply-temp": [44.0] * 8,
            "chilled-water-return-temp": [45.0] * 8,
        }
    )
    r = _run(df)
    assert r.status == "SKIPPED_MISSING_ROLES"
    assert (r.fault_hours or 0) == 0


def test_proven_off_zeros_not_fault_hours():
    df = _frame(
        **{
            "chilled-water-supply-temp": [44.0] * 12,
            "chilled-water-return-temp": [45.0] * 12,
            "chiller-status": [0] * 12,
            "chiller-current": [0.0] * 12,
            "chiller-power": [0.0] * 12,
        }
    )
    r = _run(df)
    assert r.status == "SKIPPED_EQUIPMENT_OFF"
    assert (r.fault_hours or 0) == 0


def test_proven_on_low_dt_faults():
    df = _frame(
        **{
            "chilled-water-supply-temp": [44.0] * 12,
            "chilled-water-return-temp": [45.0] * 12,
            "chiller-status": [1] * 12,
        }
    )
    r = _run(df)
    assert r.status == "FAULT"
    assert (r.fault_hours or 0) > 0


def test_partial_proof_coverage():
    on = [0, 0, 0, 1, 1, 1, 1, 1, 1, 0, 0, 0]
    df = _frame(
        **{
            "chilled-water-supply-temp": [44.0] * 12,
            "chilled-water-return-temp": [45.0] * 12,
            "chiller-status": on,
        }
    )
    r = _run(df)
    assert r.status in {"FAULT", "PASS", "SKIPPED_EQUIPMENT_OFF"}
    if r.status == "FAULT":
        assert r.fault_hours < 12 * 300 / 3600.0


def test_conflicting_command_status_prefers_status():
    df = _frame(
        **{
            "chilled-water-supply-temp": [44.0] * 8,
            "chilled-water-return-temp": [45.0] * 8,
            "chiller-status": [0] * 8,
            "chw-pump-cmd": [1.0] * 8,
        }
    )
    r = _run(df)
    assert r.status == "SKIPPED_EQUIPMENT_OFF"
    assert (r.fault_hours or 0) == 0


def test_sentinel_contaminated_proof_skips():
    df = _frame(
        **{
            "chilled-water-supply-temp": [44.0] * 8,
            "chilled-water-return-temp": [45.0] * 8,
            "chiller-status": [999.0] * 8,
        }
    )
    r = _run(df)
    assert r.status == "SKIPPED_MISSING_ROLES"
    assert (r.fault_hours or 0) == 0
