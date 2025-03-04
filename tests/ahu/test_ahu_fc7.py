import pytest
import pandas as pd
import numpy as np
from open_fdd.air_handling_unit.faults import FaultConditionSeven
from open_fdd.core.exceptions import MissingColumnError, InvalidParameterError


def test_fc7_initialization():
    """Test initialization of FaultConditionSeven with valid parameters."""
    config = {
        "SAT_COL": "sat",
        "SAT_SETPOINT_COL": "sat_setpoint",
        "HEATING_SIG_COL": "heating_sig",
        "SUPPLY_VFD_SPEED_COL": "supply_vfd_speed",
        "SUPPLY_DEGF_ERR_THRES": 0.5,
        "TROUBLESHOOT_MODE": False,
        "ROLLING_WINDOW_SIZE": 5
    }
    fault = FaultConditionSeven(config)
    
    # Check base attributes
    assert fault.troubleshoot_mode is False
    assert fault.rolling_window_size == 5
    
    # Check specific attributes
    assert fault.sat_col == "sat"
    assert fault.sat_setpoint_col == "sat_setpoint"
    assert fault.heating_sig_col == "heating_sig"
    assert fault.supply_vfd_speed_col == "supply_vfd_speed"
    assert fault.supply_degf_err_thres == 0.5


def test_fc7_missing_required_columns():
    """Test initialization with missing required columns."""
    config = {
        "SAT_COL": None,  # Missing required column
        "SAT_SETPOINT_COL": "sat_setpoint",
        "HEATING_SIG_COL": "heating_sig",
        "SUPPLY_VFD_SPEED_COL": "supply_vfd_speed",
        "SUPPLY_DEGF_ERR_THRES": 0.5
    }
    with pytest.raises(MissingColumnError):
        FaultConditionSeven(config)


def test_fc7_invalid_threshold():
    """Test initialization with invalid threshold parameters."""
    config = {
        "SAT_COL": "sat",
        "SAT_SETPOINT_COL": "sat_setpoint",
        "HEATING_SIG_COL": "heating_sig",
        "SUPPLY_VFD_SPEED_COL": "supply_vfd_speed",
        "SUPPLY_DEGF_ERR_THRES": "invalid"  # Should be float
    }
    with pytest.raises(InvalidParameterError):
        FaultConditionSeven(config)


def test_fc7_apply():
    """Test the apply method with sample data."""
    # Create sample data
    dates = pd.date_range(start="2024-01-01", periods=10, freq="1min")
    df = pd.DataFrame(index=dates)
    df["sat"] = [20.0, 21.0, 22.0, 23.0, 24.0, 25.0, 26.0, 27.0, 28.0, 29.0]
    df["sat_setpoint"] = [25.0, 25.0, 25.0, 25.0, 25.0, 25.0, 25.0, 25.0, 25.0, 25.0]
    df["heating_sig"] = [0.5, 0.5, 0.5, 0.5, 0.5, 0.5, 0.5, 0.5, 0.5, 0.5]
    df["supply_vfd_speed"] = [0.5, 0.5, 0.5, 0.5, 0.5, 0.5, 0.5, 0.5, 0.5, 0.5]

    # Initialize fault condition
    config = {
        "SAT_COL": "sat",
        "SAT_SETPOINT_COL": "sat_setpoint",
        "HEATING_SIG_COL": "heating_sig",
        "SUPPLY_VFD_SPEED_COL": "supply_vfd_speed",
        "SUPPLY_DEGF_ERR_THRES": 0.5,
        "TROUBLESHOOT_MODE": False,
        "ROLLING_WINDOW_SIZE": 5
    }
    fault = FaultConditionSeven(config)

    # Apply fault condition
    result = fault.apply(df)

    # Check that fc7_flag column exists and contains only 0s and 1s
    assert "fc7_flag" in result.columns
    assert result["fc7_flag"].isin([0, 1]).all()


def test_fc7_apply_with_fault():
    """Test the apply method with data that should trigger a fault."""
    # Create sample data with conditions that should trigger a fault
    dates = pd.date_range(start="2024-01-01", periods=10, freq="1min")
    df = pd.DataFrame(index=dates)
    df["sat"] = [20.0, 20.0, 20.0, 20.0, 20.0, 20.0, 20.0, 20.0, 20.0, 20.0]  # Low supply temp
    df["sat_setpoint"] = [25.0, 25.0, 25.0, 25.0, 25.0, 25.0, 25.0, 25.0, 25.0, 25.0]  # High setpoint
    df["heating_sig"] = [1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0]  # Full heating
    df["supply_vfd_speed"] = [0.5, 0.5, 0.5, 0.5, 0.5, 0.5, 0.5, 0.5, 0.5, 0.5]  # Fan running

    # Initialize fault condition
    config = {
        "SAT_COL": "sat",
        "SAT_SETPOINT_COL": "sat_setpoint",
        "HEATING_SIG_COL": "heating_sig",
        "SUPPLY_VFD_SPEED_COL": "supply_vfd_speed",
        "SUPPLY_DEGF_ERR_THRES": 0.5,
        "TROUBLESHOOT_MODE": False,
        "ROLLING_WINDOW_SIZE": 5
    }
    fault = FaultConditionSeven(config)

    # Apply fault condition
    result = fault.apply(df)

    # Check that fault is detected (fc7_flag should be 1)
    assert result["fc7_flag"].sum() > 0  # At least one fault should be detected 