"""Smoke tests for Engineering Findings reporting package."""

from __future__ import annotations

import pandas as pd

from open_fdd.reporting import build_engineering_findings
from open_fdd.rules.base import RuleResult


def test_build_engineering_findings_from_synthetic_result():
    idx = pd.date_range("2026-01-01", periods=4, freq="5min", tz="UTC")
    mask = pd.Series([False, True, True, False], index=idx)
    result = RuleResult(
        rule_id="SCHED-1",
        equipment_id="AHU_1",
        status="FAULT",
        applicable=True,
        equipment_type="AHU",
        fault_hours=0.5,
        fault_pct=50.0,
        sample_count=4,
        fault_sample_count=2,
        confirmed_fault=mask,
        raw_fault=mask,
    )
    artifacts = build_engineering_findings(
        building="Test Building",
        checklist=None,
        rule_results=[result],
        max_findings=5,
    )
    assert artifacts is not None
    assert hasattr(artifacts, "findings")
