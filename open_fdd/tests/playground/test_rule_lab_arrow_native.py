from __future__ import annotations

from open_fdd.arrow_runtime.backend import lint_arrow_rule, run_arrow_rule
from open_fdd.arrow_runtime.testing import sample_hvac_table
from open_fdd.playground.arrow_templates import DEFAULT_ARROW_RULE, ARROW_TEMPLATES


def test_default_arrow_template_lints():
    lint = lint_arrow_rule(DEFAULT_ARROW_RULE)
    assert lint["ok"]


def test_templates_execute():
    table = sample_hvac_table(30, seed=3)
    for tpl in ARROW_TEMPLATES:
        cfg = {
            "max_zone_temp": 72,
            "min_airflow_cfm": 500,
            "fan_on_threshold": 0.5,
            "economizer_oat_limit": 65,
            "cooling_threshold": 0.5,
            "min_oa_damper_cmd": 0.2,
            "heat_threshold": 0.1,
            "cool_threshold": 0.1,
            "min_value": 0,
            "max_value": 100,
        }
        result = run_arrow_rule(tpl["code"], table, cfg, rule_id=tpl["id"])
        assert result.row_count == 30
