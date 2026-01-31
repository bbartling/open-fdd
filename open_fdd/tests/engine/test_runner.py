"""Tests for config-driven RuleRunner."""

import pandas as pd
import pytest

from open_fdd.engine import RuleRunner


@pytest.fixture
def sample_df():
    """Sample AHU-style DataFrame."""
    return pd.DataFrame({
        "timestamp": pd.date_range(start="2023-01-01", periods=20, freq="15min"),
        "duct_static": [0.4, 0.35, 0.3, 0.25, 0.2] * 4,
        "duct_static_setpoint": [0.5] * 20,
        "supply_vfd_speed": [0.95, 0.96, 0.97, 0.98, 0.99] * 4,
        "sat": [54, 55, 56, 57, 58] * 4,
        "rat": [70] * 20,
    })


@pytest.fixture
def fc1_rule():
    """AHU FC1 rule config."""
    return {
        "name": "low_duct_static_at_max_fan",
        "type": "expression",
        "flag": "fc1_flag",
        "inputs": {
            "duct_static": {"column": "duct_static"},
            "duct_static_setpoint": {"column": "duct_static_setpoint"},
            "supply_vfd_speed": {"column": "supply_vfd_speed"},
        },
        "params": {
            "static_err_thres": 0.1,
            "vfd_max": 0.95,
            "vfd_err_thres": 0.05,
        },
        "expression": "(duct_static < duct_static_setpoint - static_err_thres) & (supply_vfd_speed >= vfd_max - vfd_err_thres)",
    }


def test_runner_expression_rule(sample_df, fc1_rule):
    """RuleRunner evaluates expression rules correctly."""
    runner = RuleRunner(rules=[fc1_rule])
    result = runner.run(sample_df)
    assert "fc1_flag" in result.columns
    # duct_static 0.2 < 0.5-0.1=0.4, vfd 0.99 >= 0.95-0.05=0.9 -> fault
    assert result["fc1_flag"].sum() > 0


def test_runner_bounds_rule(sample_df):
    """RuleRunner evaluates bounds rules correctly."""
    rule = {
        "name": "bounds",
        "type": "bounds",
        "flag": "bounds_flag",
        "inputs": {"sat": {"column": "sat", "bounds": [40, 60]}},
    }
    runner = RuleRunner(rules=[rule])
    result = runner.run(sample_df)
    assert "bounds_flag" in result.columns
    # sat has values 54-58, all in [40,60], so no fault
    assert result["bounds_flag"].sum() == 0


def test_runner_bounds_out_of_range(sample_df):
    """Bounds rule flags values outside range."""
    rule = {
        "name": "bounds",
        "type": "bounds",
        "flag": "bounds_flag",
        "inputs": {"sat": {"column": "sat", "bounds": [40, 55]}},
    }
    runner = RuleRunner(rules=[rule])
    result = runner.run(sample_df)
    # sat has 56,57,58 which are > 55
    assert result["bounds_flag"].sum() > 0


def test_runner_flatline_rule():
    """RuleRunner evaluates flatline rules."""
    df = pd.DataFrame({
        "sat": [50.0] * 20,  # completely flat
    })
    rule = {
        "name": "flatline",
        "type": "flatline",
        "flag": "flatline_flag",
        "inputs": {"sat": {"column": "sat"}},
        "params": {"tolerance": 0.001, "window": 5},
    }
    runner = RuleRunner(rules=[rule])
    result = runner.run(df)
    assert "flatline_flag" in result.columns
    assert result["flatline_flag"].sum() > 0


def test_runner_from_dir(sample_df):
    """RuleRunner loads rules from directory."""
    from pathlib import Path
    rules_dir = Path(__file__).resolve().parent.parent.parent / "rules"
    if rules_dir.is_dir():
        runner = RuleRunner(rules_path=rules_dir)
        result = runner.run(sample_df, skip_missing_columns=True)
        assert len(result.columns) > len(sample_df.columns)


def test_runner_fc3_expression():
    """FC3 mix temp too high - fault when MAT > max(RAT, OAT)."""
    df = pd.DataFrame({
        "mat": [80.0, 81.0, 79.0],
        "rat": [70.0, 70.5, 71.0],
        "oat": [50.0, 51.0, 52.0],
        "supply_vfd_speed": [0.9, 0.9, 0.9],
    })
    rule = {
        "name": "mix_temp_too_high",
        "type": "expression",
        "flag": "fc3_flag",
        "inputs": {
            "mat": {"column": "mat"},
            "rat": {"column": "rat"},
            "oat": {"column": "oat"},
            "supply_vfd_speed": {"column": "supply_vfd_speed"},
        },
        "params": {"mix_err_thres": 2.0, "return_err_thres": 2.0, "outdoor_err_thres": 5.0},
        "expression": "(mat - mix_err_thres > np.maximum(rat + return_err_thres, oat + outdoor_err_thres)) & (supply_vfd_speed > 0.01)",
    }
    runner = RuleRunner(rules=[rule])
    result = runner.run(df)
    assert "fc3_flag" in result.columns
    # MAT 80 > max(72, 55)=72, 81 > max(72.5, 56)=72.5, 79 > max(73, 57)=73 -> fault
    assert result["fc3_flag"].sum() >= 2


def test_runner_bounds_metric_units():
    """Bounds rule uses metric bounds when params={"units": "metric"}."""
    df = pd.DataFrame({
        "sat": [5, 70],   # 5 degC in range [4,66], 70 degC out of range
    })
    rule = {
        "name": "bounds",
        "type": "bounds",
        "flag": "bounds_flag",
        "inputs": {
            "sat": {
                "column": "sat",
                "bounds": {"imperial": [40, 150], "metric": [4, 66]},
            },
        },
    }
    runner = RuleRunner(rules=[rule])
    result = runner.run(df, params={"units": "metric"})
    assert "bounds_flag" in result.columns
    # 5 in [4,66] ok, 70 > 66 fault
    assert result["bounds_flag"].iloc[0] == 0
    assert result["bounds_flag"].iloc[1] == 1


def test_runner_fc4_hunting():
    """FC4 PID hunting - fault when excessive state changes in window."""
    # Alternate between two modes to create many state changes
    data = []
    for i in range(60):
        if i % 2 == 0:
            data.append({"economizer_sig": 0.6, "heating_sig": 0.0, "cooling_sig": 0.6, "supply_vfd_speed": 0.8})
        else:
            data.append({"economizer_sig": 0.0, "heating_sig": 0.0, "cooling_sig": 0.6, "supply_vfd_speed": 0.8})
    df = pd.DataFrame(data)
    rule = {
        "name": "excessive_state_changes",
        "type": "hunting",
        "flag": "fc4_flag",
        "inputs": {
            "economizer_sig": {"column": "economizer_sig"},
            "supply_vfd_speed": {"column": "supply_vfd_speed"},
            "heating_sig": {"column": "heating_sig"},
            "cooling_sig": {"column": "cooling_sig"},
        },
        "params": {"delta_os_max": 7, "ahu_min_oa_dpr": 0.2, "window": 60},
    }
    runner = RuleRunner(rules=[rule])
    result = runner.run(df)
    assert "fc4_flag" in result.columns
    assert result["fc4_flag"].sum() >= 1
