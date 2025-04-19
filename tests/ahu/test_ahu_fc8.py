import numpy as np
import pandas as pd
import pytest

from open_fdd.air_handling_unit.faults import FaultConditionEight
from open_fdd.core.exceptions import InvalidParameterError, MissingColumnError


def test_fc8_initialization():
    """Test initialization of FaultConditionEight with valid parameters."""
    config = {
        "MAT_COL": "mat",
        "SAT_COL": "sat",
        "ECONOMIZER_SIG_COL": "economizer_sig",
        "COOLING_SIG_COL": "cooling_sig",
        "DELTA_T_SUPPLY_FAN": 0.5,
        "MIX_DEGF_ERR_THRES": 0.5,
        "SUPPLY_DEGF_ERR_THRES": 0.5,
        "AHU_MIN_OA_DPR": 0.2,
        "TROUBLESHOOT_MODE": False,
        "ROLLING_WINDOW_SIZE": 5,
    }
    fault = FaultConditionEight(config)

    # Check base attributes
    assert fault.troubleshoot_mode is False
    assert fault.rolling_window_size == 5

    # Check specific attributes
    assert fault.mat_col == "mat"
    assert fault.sat_col == "sat"
    assert fault.economizer_sig_col == "economizer_sig"
    assert fault.cooling_sig_col == "cooling_sig"
    assert fault.delta_t_supply_fan == 0.5
    assert fault.mix_degf_err_thres == 0.5
    assert fault.supply_degf_err_thres == 0.5
    assert fault.ahu_min_oa_dpr == 0.2


def test_fc8_missing_required_columns():
    """Test initialization with missing required columns."""
    config = {
        "MAT_COL": None,  # Missing required column
        "SAT_COL": "sat",
        "ECONOMIZER_SIG_COL": "economizer_sig",
        "COOLING_SIG_COL": "cooling_sig",
        "DELTA_T_SUPPLY_FAN": 0.5,
        "MIX_DEGF_ERR_THRES": 0.5,
        "SUPPLY_DEGF_ERR_THRES": 0.5,
        "AHU_MIN_OA_DPR": 0.2,
    }
    with pytest.raises(MissingColumnError):
        FaultConditionEight(config)


def test_fc8_invalid_threshold():
    """Test initialization with invalid threshold parameters."""
    config = {
        "MAT_COL": "mat",
        "SAT_COL": "sat",
        "ECONOMIZER_SIG_COL": "economizer_sig",
        "COOLING_SIG_COL": "cooling_sig",
        "DELTA_T_SUPPLY_FAN": "invalid",  # Should be float
        "MIX_DEGF_ERR_THRES": 0.5,
        "SUPPLY_DEGF_ERR_THRES": 0.5,
        "AHU_MIN_OA_DPR": 0.2,
    }
    with pytest.raises(InvalidParameterError):
        FaultConditionEight(config)


def test_fc8_apply():
    """Test the apply method with sample data."""
    # Create sample data
    dates = pd.date_range(start="2024-01-01", periods=10, freq="1min")
    df = pd.DataFrame(index=dates)
    df["mat"] = [20.0, 21.0, 22.0, 23.0, 24.0, 25.0, 26.0, 27.0, 28.0, 29.0]
    df["sat"] = [20.0, 21.0, 22.0, 23.0, 24.0, 25.0, 26.0, 27.0, 28.0, 29.0]
    df["economizer_sig"] = [0.5, 0.5, 0.5, 0.5, 0.5, 0.5, 0.5, 0.5, 0.5, 0.5]
    df["cooling_sig"] = [0.5, 0.5, 0.5, 0.5, 0.5, 0.5, 0.5, 0.5, 0.5, 0.5]

    # Initialize fault condition
    config = {
        "MAT_COL": "mat",
        "SAT_COL": "sat",
        "ECONOMIZER_SIG_COL": "economizer_sig",
        "COOLING_SIG_COL": "cooling_sig",
        "DELTA_T_SUPPLY_FAN": 0.5,
        "MIX_DEGF_ERR_THRES": 0.5,
        "SUPPLY_DEGF_ERR_THRES": 0.5,
        "AHU_MIN_OA_DPR": 0.2,
        "TROUBLESHOOT_MODE": False,
        "ROLLING_WINDOW_SIZE": 5,
    }
    fault = FaultConditionEight(config)

    # Apply fault condition
    result = fault.apply(df)

    # Check that fc8_flag column exists and contains only 0s and 1s
    assert "fc8_flag" in result.columns
    assert result["fc8_flag"].isin([0, 1]).all()


def test_fc8_apply_with_fault():
    """Test the apply method with data that should trigger a fault."""
    # Create sample data with conditions that should trigger a fault
    dates = pd.date_range(start="2024-01-01", periods=10, freq="1min")
    df = pd.DataFrame(index=dates)
    df["mat"] = [
        20.0,
        20.0,
        20.0,
        20.0,
        20.0,
        20.0,
        20.0,
        20.0,
        20.0,
        20.0,
    ]  # Low mix temp
    df["sat"] = [
        30.0,
        30.0,
        30.0,
        30.0,
        30.0,
        30.0,
        30.0,
        30.0,
        30.0,
        30.0,
    ]  # High supply temp
    df["economizer_sig"] = [
        1.0,
        1.0,
        1.0,
        1.0,
        1.0,
        1.0,
        1.0,
        1.0,
        1.0,
        1.0,
    ]  # Full economizer
    df["cooling_sig"] = [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]  # No cooling

    # Initialize fault condition
    config = {
        "MAT_COL": "mat",
        "SAT_COL": "sat",
        "ECONOMIZER_SIG_COL": "economizer_sig",
        "COOLING_SIG_COL": "cooling_sig",
        "DELTA_T_SUPPLY_FAN": 0.5,
        "MIX_DEGF_ERR_THRES": 0.5,
        "SUPPLY_DEGF_ERR_THRES": 0.5,
        "AHU_MIN_OA_DPR": 0.2,
        "TROUBLESHOOT_MODE": False,
        "ROLLING_WINDOW_SIZE": 5,
    }
    fault = FaultConditionEight(config)

    # Apply fault condition
    result = fault.apply(df)

    # Check that fault is detected (fc8_flag should be 1)
    assert result["fc8_flag"].sum() > 0  # At least one fault should be detected
