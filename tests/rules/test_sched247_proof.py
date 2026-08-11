"""SCHED-247 ranked proof: status > command; pressure is inferred only."""

from __future__ import annotations

import pandas as pd

from open_fdd.rules import run_rule


def _run(**cols):
    n = len(next(iter(cols.values())))
    idx = pd.date_range("2026-01-01", periods=n, freq="5min", tz="UTC")
    df = pd.DataFrame(cols, index=idx)
    df.attrs["equipment_id"] = "AHU_1"
    df.attrs["equipment_type"] = "AHU"
    return run_rule(
        "SCHED-247",
        df,
        params={"always_on_pct": 0.5, "confirm_seconds": 0, "confirm_min": 0},
        poll_seconds=300.0,
        require_operational_gates=False,
    )


def test_status_always_on_faults_with_proof_fields():
    r = _run(**{"fan-status": [1] * 10})
    assert r.status == "FAULT"
    assert r.metrics["proof_source"] == "fan-status"
    assert r.metrics["proof_confidence"] == 1.0
    assert r.metrics["proven_runtime_hours"] > 0
    assert r.metrics["inferred_runtime_hours"] == 0


def test_pressure_alone_does_not_fault():
    r = _run(**{"duct-static-pressure": [1.5] * 10})
    assert r.status == "PASS"
    assert r.metrics["inferred_runtime_hours"] > 0
    assert r.metrics["proven_runtime_hours"] == 0


def test_command_used_when_status_absent():
    r = _run(**{"fan-cmd": [1.0] * 10})
    assert r.status == "FAULT"
    assert "cmd" in r.metrics["proof_source"]
    assert r.metrics["proof_confidence"] == 0.5


def test_status_off_command_on_is_conflict_not_or():
    r = _run(**{"fan-status": [0] * 10, "fan-cmd": [1.0] * 10})
    assert r.status == "PASS"
    assert r.metrics["conflicting_signal_hours"] > 0
    assert r.metrics["proof_source"] == "fan-status"
