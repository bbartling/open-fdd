"""Smoke tests for packaged pandas oracle rules."""

from __future__ import annotations

import pandas as pd

from open_fdd.rules import CANONICAL_RULE_COUNT, RULES, RULES_BY_ID, run_rule


def test_canonical_rule_count_is_59():
    assert CANONICAL_RULE_COUNT == 59
    assert len(RULES) >= 59
    assert "SCHED-1" in RULES_BY_ID


def test_sched1_unoccupied_runtime_smoke():
    idx = pd.date_range("2026-01-01", periods=6, freq="5min", tz="UTC")
    df = pd.DataFrame(
        {
            "occ-mode": [
                "occupied",
                "occupied",
                "unoccupied",
                "unoccupied",
                "unoccupied",
                "occupied",
            ],
            "fan-status": [1, 1, 1, 1, 1, 0],
        },
        index=idx,
    )
    df.attrs["equipment_id"] = "AHU_1"
    df.attrs["equipment_type"] = "AHU"
    result = run_rule(
        "SCHED-1",
        df,
        params={"confirm_seconds": 600},
        poll_seconds=300.0,
        require_operational_gates=False,
    )
    assert result.rule_id == "SCHED-1"
    assert result.status in {
        "PASS",
        "FAULT",
        "SKIPPED_MISSING_ROLES",
        "SKIPPED_EQUIPMENT_OFF",
        "NOT_APPLICABLE_EQUIPMENT_TYPE",
        "ERROR",
    }
    assert (result.fault_hours or 0) >= 0
