"""#1723: SQL active_hours (the fault_pct denominator of run-proof gated rules) must equal the pandas denominator.

pandas divides those rules by their proven-on time too (``finalize_result(pct_mask=...)``, reported as
``metrics["active_hours"]``), so a difference beyond ``Policy.active_tol_h`` now fails the verdict (it was informational
under #1631). A rule pandas did not assess (SKIPPED) has no denominator and is not compared.
"""

import pandas as pd

from open_fdd.parity.policy import Policy, compare
from open_fdd.rules.base import finalize_result


def _rows(active):
    return {"R": [{"equipment_id": "E", "fault_hours": 2.0, "covered_hours": 48.0, "active_hours": active, "fault_pct": 4.0}]}


REF = {"R": {"E": {"pandas": 2.0, "status": "FAULT", "active_samples": 240}}}   # 240 x 300 s = 20 h
REF_HOURS = {"R": {"E": {"pandas": 2.0, "status": "FAULT", "active_samples": 240, "active_hours": 42.0}}}


def test_a_denominator_difference_fails_the_verdict():
    v = compare(_rows(30.0), REF_HOURS, Policy())
    assert not v.ok and v.matched == 1
    assert v.active_hours_mismatches == ["R/E: SQL active_hours 30.00 h vs pandas active 42.00 h"]
    assert v.per_rule["R"]["E"]["sql_active_hours"] == 30.0 and v.per_rule["R"]["E"]["pandas_active_hours"] == 42.0
    assert "active_hours_mismatches" in v.to_dict()


def test_pandas_active_hours_is_preferred_over_the_gate_sample_count():
    v = compare(_rows(42.0), REF_HOURS, Policy())
    assert v.ok and v.active_hours_mismatches == []
    # without active_hours the gate sample count is the fallback (240 x 300 s = 20 h)
    assert compare(_rows(42.0), REF, Policy()).active_hours_mismatches


def test_within_tolerance_is_quiet():
    assert compare(_rows(42.5), REF_HOURS, Policy()).active_hours_mismatches == []
    assert compare(_rows(42.5), REF_HOURS, Policy(active_tol_h=0.25)).active_hours_mismatches


def test_a_pandas_skip_is_not_compared():
    skipped = {"R": {"E": {"pandas": None, "status": "SKIPPED_MISSING_ROLES", "active_samples": 0}}}
    rows = {"R": [{"equipment_id": "E", "fault_hours": 0.0, "covered_hours": 42.0, "active_hours": 42.0, "fault_pct": 0.0}]}
    assert compare(rows, skipped, Policy()).active_hours_mismatches == []


def test_finalize_result_divides_by_the_pct_mask():
    idx = pd.date_range("2026-01-05", periods=24, freq="5min")
    raw = pd.Series([True] * 6 + [False] * 18, index=idx)
    gate = pd.Series([True] * 12 + [False] * 12, index=idx)     # the rule's own gate: 1 h
    proof = pd.Series([True] * 24, index=idx)                    # proven on: 2 h
    own = finalize_result("R", "E", raw, 300.0, 0.0, active_mask=gate)
    run = finalize_result("R", "E", raw, 300.0, 0.0, active_mask=gate, pct_mask=proof)
    assert own.fault_hours == run.fault_hours == 0.5               # the fault side is unchanged
    # 24 proven samples hold 23 forward intervals (the last sample owns none): 23 x 300 s = 1.9167 h
    assert own.fault_pct == 50.0
    assert abs(run.metrics["active_hours"] - 23 * 300 / 3600) < 1e-6 and "active_hours" not in own.metrics
    assert run.fault_pct == round(100 * 0.5 / (23 * 300 / 3600), 2)
