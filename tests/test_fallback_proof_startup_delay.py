"""#1631: when a hydronic rule's own proof roles are absent, the runner falls back to the resolved run proof. That fallback
gets the rule's startup delay too (as the hydronic proof it replaces), so the first minutes after the plant starts are
not assessed."""

import pandas as pd

from open_fdd.rules import RULES_BY_ID
from open_fdd.rules.runner import run_cookbook_rule


def _frame():
    idx = pd.date_range("2026-01-01", periods=49, freq="5min", tz="UTC")
    proof = [0.0] * 12 + [1.0] * 37                      # off for the first hour, then on
    d = pd.DataFrame({
        "supply_hot_water_temperature": 85.0,
        "hot_water_reset_request_count": 0.0,
        "operating_status": proof,
    }, index=idx)
    d.attrs.update({"run_proof_resolved": True, "equipment_id": "plant-1", "equipment_type": "BOILER"})
    return d


def _run(params=None):
    rule = RULES_BY_ID["TRIM-3"]
    return run_cookbook_rule(rule, _frame(), equipment_id="plant-1", equipment_kind="boiler", poll_seconds=300.0,
                             params_by_rule={rule.id: params or {}}, require_operational_gates=True)


def test_fallback_proof_applies_the_startup_delay():
    res = _run()
    assert res.metrics.get("startup_delay_seconds") == 600.0
    # the same holdoff the ordinary hydronic gate applies (operational_gate.apply_startup_delay), fewer than 37 proven
    from open_fdd.rules.operational_gate import apply_startup_delay
    from open_fdd.run_proof import proof_on

    expected = int(apply_startup_delay(proof_on(_frame()["operating_status"]), 300.0, 600.0).sum())
    assert expected < 37
    assert res.metrics["active_sample_count"] == expected


def test_startup_delay_zero_keeps_every_proven_sample():
    assert _run({"startup_delay_min": 0}).metrics["active_sample_count"] == 37
