"""#1727: run_rule finds CUSTOM-* rules added to custom_rules.CUSTOM_RULES at run time (the write-a-rule docs example)."""
import pandas as pd

from open_fdd.rules import run_rule
from open_fdd.rules.custom_boilerplate import make_custom_rule
from open_fdd.rules.custom_rules import CUSTOM_RULES


def test_run_rule_finds_a_custom_rule_appended_after_import():
    rule = make_custom_rule(
        rule_id="CUSTOM-TEST-LATE", title="late custom rule", equation="SAT > 25 °C",
        compute=lambda d, p, poll: pd.to_numeric(d["discharge_air_temperature"], errors="coerce") > 25.0,
        required_roles=["discharge_air_temperature"], equipment_kinds=["ahu"])
    CUSTOM_RULES.append(rule)
    try:
        idx = pd.date_range("2026-01-05", periods=24, freq="5min", tz="UTC")
        df = pd.DataFrame({"discharge_air_temperature": [20.0] * 12 + [27.0] * 12}, index=idx)
        res = run_rule("CUSTOM-TEST-LATE", df, params={"confirm_min": 0}, equipment_type="AHU")
        assert res.status == "FAULT" and res.fault_hours > 0
    finally:
        CUSTOM_RULES.remove(rule)


def test_the_docs_example_runs_and_a_missing_fan_status_is_skipped():
    """docs/rules/write-a-rule.md: the published block prints FAULT 1.83; without the required fan status the rule is
    SKIPPED (never an ERROR, never assumed on)."""
    import re
    from pathlib import Path

    page = (Path(__file__).resolve().parents[1] / "docs/rules/write-a-rule.md").read_text(encoding="utf-8")
    ns: dict = {}
    before = len(CUSTOM_RULES)
    try:
        exec(re.findall(r"```python\n(.*?)```", page, re.S)[0], ns)
        r = ns["r"]
        assert (r.status, r.fault_hours) == ("FAULT", 1.83)
        missing = run_rule("CUSTOM-SAT-HIGH", ns["df"].drop(columns="supply_fan_operating_status"), params={"confirm_min": 10},
                           equipment_type="AHU")
        assert str(missing.status).startswith("SKIPPED") and "supply_fan_operating_status" in (missing.notes or "")
    finally:
        del CUSTOM_RULES[before:]
