"""DataFrame input validation for rules."""

import pandas as pd
import pytest

from open_fdd.engine.input_validation import (
    raise_if_strict_issues,
    validate_rule_inputs,
)


def test_validate_off_returns_empty():
    df = pd.DataFrame({"a": [1, 2]})
    assert (
        validate_rule_inputs(
            df, {"x": "a"}, rule_name="r", timestamp_col=None, mode="off"
        )
        == []
    )


def test_validate_strict_missing_column():
    df = pd.DataFrame({"a": [1.0]})
    issues = validate_rule_inputs(
        df,
        {"SAT": "missing_col"},
        rule_name="high_temp",
        timestamp_col="ts",
        mode="strict",
    )
    assert any("missing column" in m for m in issues)
    with pytest.raises(ValueError, match="FDD input validation failed"):
        raise_if_strict_issues(issues)


def test_validate_strict_non_numeric_column():
    df = pd.DataFrame({"bad": ["x", "y", "z"]})
    issues = validate_rule_inputs(
        df,
        {"sig": "bad"},
        rule_name="r1",
        timestamp_col=None,
        mode="strict",
    )
    assert len(issues) >= 1
    with pytest.raises(ValueError):
        raise_if_strict_issues(issues)


def test_validate_skips_timestamp_col():
    df = pd.DataFrame(
        {"timestamp": pd.date_range("2024-01-01", periods=3, freq="h"), "x": [1.0, 2, 3]}
    )
    issues = validate_rule_inputs(
        df,
        {"t": "timestamp", "x": "x"},
        rule_name="r",
        timestamp_col="timestamp",
        mode="strict",
    )
    assert not any("timestamp" in m and "non-numeric" in m for m in issues)


def test_validate_numeric_ok():
    df = pd.DataFrame({"sat": [55.0, 56.0]})
    issues = validate_rule_inputs(
        df,
        {"Supply_Air_Temperature_Sensor": "sat"},
        rule_name="bounds",
        timestamp_col=None,
        mode="strict",
    )
    assert issues == []
