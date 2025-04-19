import pytest
import pandas as pd
from open_fdd.air_handling_unit.faults import FaultConditionNine
from open_fdd.core.exceptions import MissingColumnError, InvalidParameterError


def test_fc9_initialization():
    """Test initialization of FaultConditionNine with valid parameters."""
    config = {
        "SAT_SETPOINT_COL": "sat_setpoint",
        "OAT_COL": "oat",
        "COOLING_SIG_COL": "cooling_sig",
        "ECONOMIZER_SIG_COL": "economizer_sig",
        "DELTA_T_SUPPLY_FAN": 0.5,
        "OUTDOOR_DEGF_ERR_THRES": 0.5,
        "SUPPLY_DEGF_ERR_THRES": 0.5,
        "AHU_MIN_OA_DPR": 0.2,
        "TROUBLESHOOT_MODE": False,
        "ROLLING_WINDOW_SIZE": 5,
    }
    fault = FaultConditionNine(config)

    # Check base attributes
    assert fault.troubleshoot_mode is False
    assert fault.rolling_window_size == 5

    # Check specific attributes
    assert fault.sat_setpoint_col == "sat_setpoint"
    assert fault.oat_col == "oat"
    assert fault.cooling_sig_col == "cooling_sig"
    assert fault.economizer_sig_col == "economizer_sig"
    assert fault.delta_t_supply_fan == 0.5
    assert fault.outdoor_degf_err_thres == 0.5
    assert fault.supply_degf_err_thres == 0.5
    assert fault.ahu_min_oa_dpr == 0.2


def test_fc9_missing_required_columns():
    """Test initialization with missing required columns."""
    config = {
        "SAT_SETPOINT_COL": None,  # Missing required column
        "OAT_COL": "oat",
        "COOLING_SIG_COL": "cooling_sig",
        "ECONOMIZER_SIG_COL": "economizer_sig",
        "DELTA_T_SUPPLY_FAN": 0.5,
        "OUTDOOR_DEGF_ERR_THRES": 0.5,
        "SUPPLY_DEGF_ERR_THRES": 0.5,
        "AHU_MIN_OA_DPR": 0.2,
    }
    with pytest.raises(MissingColumnError):
        FaultConditionNine(config)


def test_fc9_invalid_threshold():
    """Test initialization with invalid threshold parameters."""
    config = {
        "SAT_SETPOINT_COL": "sat_setpoint",
        "OAT_COL": "oat",
        "COOLING_SIG_COL": "cooling_sig",
        "ECONOMIZER_SIG_COL": "economizer_sig",
        "DELTA_T_SUPPLY_FAN": "invalid",  # Should be float
        "OUTDOOR_DEGF_ERR_THRES": 0.5,
        "SUPPLY_DEGF_ERR_THRES": 0.5,
        "AHU_MIN_OA_DPR": 0.2,
    }
    with pytest.raises(InvalidParameterError):
        FaultConditionNine(config)


def test_fc9_apply():
    """Test the apply method with sample data."""
    # Create sample data
    dates = pd.date_range(start="2024-01-01", periods=10, freq="1min")
    df = pd.DataFrame(index=dates)
    df["sat_setpoint"] = [25.0, 25.0, 25.0, 25.0, 25.0, 25.0, 25.0, 25.0, 25.0, 25.0]
    df["oat"] = [20.0, 21.0, 22.0, 23.0, 24.0, 25.0, 26.0, 27.0, 28.0, 29.0]
    df["cooling_sig"] = [0.5, 0.5, 0.5, 0.5, 0.5, 0.5, 0.5, 0.5, 0.5, 0.5]
    df["economizer_sig"] = [0.5, 0.5, 0.5, 0.5, 0.5, 0.5, 0.5, 0.5, 0.5, 0.5]

    # Initialize fault condition
    config = {
        "SAT_SETPOINT_COL": "sat_setpoint",
        "OAT_COL": "oat",
        "COOLING_SIG_COL": "cooling_sig",
        "ECONOMIZER_SIG_COL": "economizer_sig",
        "DELTA_T_SUPPLY_FAN": 0.5,
        "OUTDOOR_DEGF_ERR_THRES": 0.5,
        "SUPPLY_DEGF_ERR_THRES": 0.5,
        "AHU_MIN_OA_DPR": 0.2,
        "TROUBLESHOOT_MODE": False,
        "ROLLING_WINDOW_SIZE": 5,
    }
    fault = FaultConditionNine(config)

    # Apply fault condition
    result = fault.apply(df)

    # Check that fc9_flag column exists and contains only 0s and 1s
    assert "fc9_flag" in result.columns
    assert result["fc9_flag"].isin([0, 1]).all()


def test_fc9_apply_with_fault():
    """Test the apply method with data that should trigger a fault."""
    # Create sample data with conditions that should trigger a fault
    dates = pd.date_range(start="2024-01-01", periods=10, freq="1min")
    df = pd.DataFrame(index=dates)
    df["sat_setpoint"] = [
        25.0,
        25.0,
        25.0,
        25.0,
        25.0,
        25.0,
        25.0,
        25.0,
        25.0,
        25.0,
    ]  # Low setpoint
    df["oat"] = [
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
    ]  # High outdoor temp
    df["cooling_sig"] = [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]  # No cooling
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

    # Initialize fault condition
    config = {
        "SAT_SETPOINT_COL": "sat_setpoint",
        "OAT_COL": "oat",
        "COOLING_SIG_COL": "cooling_sig",
        "ECONOMIZER_SIG_COL": "economizer_sig",
        "DELTA_T_SUPPLY_FAN": 0.5,
        "OUTDOOR_DEGF_ERR_THRES": 0.5,
        "SUPPLY_DEGF_ERR_THRES": 0.5,
        "AHU_MIN_OA_DPR": 0.2,
        "TROUBLESHOOT_MODE": False,
        "ROLLING_WINDOW_SIZE": 5,
    }
    fault = FaultConditionNine(config)

    # Apply fault condition
    result = fault.apply(df)

    # Check that fault is detected (fc9_flag should be 1)
    assert result["fc9_flag"].sum() > 0  # At least one fault should be detected
