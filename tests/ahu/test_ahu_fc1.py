import numpy as np
import pandas as pd
import pytest

from open_fdd.air_handling_unit.faults import FaultConditionOne
from open_fdd.core.exceptions import InvalidParameterError, MissingColumnError


def test_fc1_initialization():
    """Test initialization of FaultConditionOne with valid parameters."""
    config = {
        "DUCT_STATIC_COL": "duct_static",
        "SUPPLY_VFD_SPEED_COL": "supply_vfd_speed",
        "DUCT_STATIC_SETPOINT_COL": "duct_static_setpoint",
        "DUCT_STATIC_INCHES_ERR_THRES": 0.5,
        "VFD_SPEED_PERCENT_MAX": 100.0,
        "VFD_SPEED_PERCENT_ERR_THRES": 5.0,
        "TROUBLESHOOT_MODE": False,
        "ROLLING_WINDOW_SIZE": 5,
    }
    fault = FaultConditionOne(config)

    # Check base attributes
    assert fault.troubleshoot_mode is False
    assert fault.rolling_window_size == 5

    # Check specific attributes
    assert fault.duct_static_col == "duct_static"
    assert fault.supply_vfd_speed_col == "supply_vfd_speed"
    assert fault.duct_static_setpoint_col == "duct_static_setpoint"
    assert fault.duct_static_inches_err_thres == 0.5
    assert fault.vfd_speed_percent_max == 100.0
    assert fault.vfd_speed_percent_err_thres == 5.0


def test_fc1_missing_required_columns():
    """Test initialization with missing required columns."""
    config = {
        "DUCT_STATIC_COL": None,  # Missing required column
        "SUPPLY_VFD_SPEED_COL": "supply_vfd_speed",
        "DUCT_STATIC_SETPOINT_COL": "duct_static_setpoint",
        "DUCT_STATIC_INCHES_ERR_THRES": 0.5,
        "VFD_SPEED_PERCENT_MAX": 100.0,
        "VFD_SPEED_PERCENT_ERR_THRES": 5.0,
    }
    with pytest.raises(MissingColumnError):
        FaultConditionOne(config)


def test_fc1_apply():
    """Test the apply method with sample data."""
    # Create sample data
    dates = pd.date_range(start="2024-01-01", periods=10, freq="1min")
    df = pd.DataFrame(index=dates)
    df["duct_static"] = [1.0, 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.7, 1.8, 1.9]
    df["supply_vfd_speed"] = [
        0.95,
        0.96,
        0.97,
        0.98,
        0.99,
        1.0,
        1.0,
        1.0,
        1.0,
        1.0,
    ]
    df["duct_static_setpoint"] = [2.0, 2.0, 2.0, 2.0, 2.0, 2.0, 2.0, 2.0, 2.0, 2.0]

    # Initialize fault condition
    config = {
        "DUCT_STATIC_COL": "duct_static",
        "SUPPLY_VFD_SPEED_COL": "supply_vfd_speed",
        "DUCT_STATIC_SETPOINT_COL": "duct_static_setpoint",
        "DUCT_STATIC_INCHES_ERR_THRES": 0.5,
        "VFD_SPEED_PERCENT_MAX": 100.0,
        "VFD_SPEED_PERCENT_ERR_THRES": 5.0,
        "TROUBLESHOOT_MODE": False,
        "ROLLING_WINDOW_SIZE": 5,
    }
    fault = FaultConditionOne(config)

    # Apply fault condition
    result = fault.apply(df)

    # Check that fc1_flag column exists and contains only 0s and 1s
    assert "fc1_flag" in result.columns
    assert result["fc1_flag"].isin([0, 1]).all()


def test_fc1_apply_with_fault():
    """Test the apply method with data that should trigger a fault."""
    # Create sample data with conditions that should trigger a fault
    dates = pd.date_range(start="2024-01-01", periods=10, freq="1min")
    df = pd.DataFrame(index=dates)
    df["duct_static"] = [
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
    ]  # Low static pressure
    df["supply_vfd_speed"] = [
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
    ]  # Full speed
    df["duct_static_setpoint"] = [
        2.0,
        2.0,
        2.0,
        2.0,
        2.0,
        2.0,
        2.0,
        2.0,
        2.0,
        2.0,
    ]  # High setpoint

    # Initialize fault condition
    config = {
        "DUCT_STATIC_COL": "duct_static",
        "SUPPLY_VFD_SPEED_COL": "supply_vfd_speed",
        "DUCT_STATIC_SETPOINT_COL": "duct_static_setpoint",
        "DUCT_STATIC_INCHES_ERR_THRES": 0.5,
        "VFD_SPEED_PERCENT_MAX": 100.0,
        "VFD_SPEED_PERCENT_ERR_THRES": 5.0,
        "TROUBLESHOOT_MODE": False,
        "ROLLING_WINDOW_SIZE": 5,
    }
    fault = FaultConditionOne(config)

    # Apply fault condition
    result = fault.apply(df)

    # Check that fault is detected (fc1_flag should be 1)
    assert result["fc1_flag"].sum() > 0  # At least one fault should be detected
