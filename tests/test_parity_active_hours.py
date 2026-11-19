"""#1631: the parity verdict reports SQL active_hours (the fault_pct denominator) against pandas active time, as
information: a gated rule whose own pandas gate differs from the run proof shows up, and it never fails the verdict."""

from open_fdd.parity.policy import Policy, compare


def _rows(active):
    return {"R": [{"equipment_id": "E", "fault_hours": 2.0, "covered_hours": 48.0, "active_hours": active, "fault_pct": 4.0}]}


REF = {"R": {"E": {"pandas": 2.0, "status": "FAULT", "active_samples": 240}}}   # 240 x 300 s = 20 h


def test_a_denominator_difference_is_reported_and_does_not_fail():
    v = compare(_rows(42.0), REF, Policy())
    assert v.ok and v.matched == 1
    assert v.active_hours_mismatches == ["R/E: SQL active_hours 42.00 h vs pandas active 20.00 h"]
    assert v.per_rule["R"]["E"]["sql_active_hours"] == 42.0 and v.per_rule["R"]["E"]["pandas_active_hours"] == 20.0
    assert "active_hours_mismatches" in v.to_dict()


def test_within_tolerance_is_quiet():
    assert compare(_rows(20.5), REF, Policy()).active_hours_mismatches == []
    assert compare(_rows(20.5), REF, Policy(active_tol_h=0.25)).active_hours_mismatches
