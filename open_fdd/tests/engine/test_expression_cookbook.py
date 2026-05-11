"""Regression tests aligned with docs/expression_rule_cookbook.md patterns."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from open_fdd.engine.checks import check_expression
from open_fdd.engine.runner import RuleRunner, load_rule


def test_cookbook_expression_with_column_map_and_flag_column():
    df = pd.DataFrame(
        {
            "timestamp": pd.to_datetime(
                ["2024-01-15 10:00", "2024-01-15 10:05", "2024-01-15 10:10"]
            ),
            "supply_air_temp": [55.0, 56.0, 80.0],
        }
    )
    rule = {
        "name": "high_sat",
        "type": "expression",
        "inputs": {"SAT": {"column": "supply_air_temp"}},
        "expression": "SAT > 70",
    }
    runner = RuleRunner(rules=[rule])
    out = runner.run(df, timestamp_col="timestamp")
    assert "high_sat_flag" in out.columns
    assert out["high_sat_flag"].tolist() == [False, False, True]


def test_cookbook_yaml_expression_fixture(tmp_path: Path):
    rule_path = tmp_path / "expr.yaml"
    rule_path.write_text(
        """
name: sat_high
type: expression
inputs:
  SAT:
    column: supply_air_temp
expression: SAT > 70
""".strip(),
        encoding="utf-8",
    )
    rule = load_rule(rule_path)
    df = pd.DataFrame({"supply_air_temp": [60.0, 75.0]})
    runner = RuleRunner(rules=[rule])
    out = runner.run(df)
    assert out["sat_high_flag"].tolist() == [False, True]


def test_cookbook_normalize_cmd_percent_heuristic():
    df = pd.DataFrame({"vfd": [0.95, 95.0, 50.0]})
    col_map = {"Supply_Fan_Speed_Command": "vfd"}
    mask = check_expression(
        df,
        "normalize_cmd(Supply_Fan_Speed_Command) >= 0.9",
        col_map,
        {},
    )
    assert mask.dtype == bool
    assert mask.any()


def test_cookbook_strict_validation_blocks_missing_columns():
    df = pd.DataFrame({"a": [1.0, 2.0]})
    rule = {
        "name": "needs_sat",
        "type": "expression",
        "inputs": {"SAT": {"column": "supply_air_temp"}},
        "expression": "SAT > 70",
    }
    runner = RuleRunner(rules=[rule])
    with pytest.raises(ValueError, match="FDD input validation failed"):
        runner.run(df, input_validation="strict")
