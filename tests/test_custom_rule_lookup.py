"""#1727: run_rule finds CUSTOM-* rules added to custom_rules.CUSTOM_RULES at run time (the write-a-rule docs example)."""
import pandas as pd

from open_fdd.rules import run_rule
from open_fdd.rules.custom_boilerplate import make_custom_rule
from open_fdd.rules.custom_rules import CUSTOM_RULES


def test_run_rule_finds_a_custom_rule_appended_after_import():
    rule = make_custom_rule(
        rule_id="CUSTOM-TEST-LATE", title="late custom rule", equation="SAT > 25 °C",
        compute=lambda d, p, poll: pd.to_numeric(d["discharge-air-temp"], errors="coerce") > 25.0,
        required_roles=["discharge-air-temp"], equipment_kinds=["ahu"])
    CUSTOM_RULES.append(rule)
    try:
        idx = pd.date_range("2026-01-05", periods=24, freq="5min", tz="UTC")
        df = pd.DataFrame({"discharge-air-temp": [20.0] * 12 + [27.0] * 12}, index=idx)
        res = run_rule("CUSTOM-TEST-LATE", df, params={"confirm_min": 0}, equipment_type="AHU")
        assert res.status == "FAULT" and res.fault_hours > 0
    finally:
        CUSTOM_RULES.remove(rule)
