import pytest
import pandas as pd
import numpy as np
from open_fdd.air_handling_unit.faults import FaultConditionTwo
from open_fdd.core.exceptions import MissingColumnError, InvalidParameterError


def test_fc2_initialization():
    """Test initialization of FaultConditionTwo with valid parameters."""
    config = {
        "MAT_COL": "mat",
        "RAT_COL": "rat",
        "OAT_COL": "oat",
        "SUPPLY_VFD_SPEED_COL": "supply_vfd_speed",
        "MIX_DEGF_ERR_THRES": 0.5,
        "OUTDOOR_DEGF_ERR_THRES": 0.5,
        "RETURN_DEGF_ERR_THRES": 0.5,
        "TROUBLESHOOT_MODE": False,
        "ROLLING_WINDOW_SIZE": 5
    }
    fault = FaultConditionTwo(config)
    
    # Check base attributes
    assert fault.troubleshoot_mode is False
    assert fault.rolling_window_size == 5
    
    # Check specific attributes
    assert fault.mat_col == "mat"
    assert fault.rat_col == "rat"
    assert fault.oat_col == "oat"
    assert fault.supply_vfd_speed_col == "supply_vfd_speed"
    assert fault.mix_degf_err_thres == 0.5
    assert fault.outdoor_degf_err_thres == 0.5
    assert fault.return_degf_err_thres == 0.5


def test_fc2_missing_required_columns():
    """Test initialization with missing required columns."""
    config = {
        "MAT_COL": None,  # Missing required column
        "RAT_COL": "rat",
        "OAT_COL": "oat",
        "SUPPLY_VFD_SPEED_COL": "supply_vfd_speed",
        "MIX_DEGF_ERR_THRES": 0.5,
        "OUTDOOR_DEGF_ERR_THRES": 0.5,
        "RETURN_DEGF_ERR_THRES": 0.5
    }
    with pytest.raises(MissingColumnError):
        FaultConditionTwo(config)


def test_fc2_apply():
    """Test the apply method with sample data."""
    # Create sample data
    dates = pd.date_range(start="2024-01-01", periods=10, freq="1min")
    df = pd.DataFrame(index=dates)
    df["mat"] = [20.0, 21.0, 22.0, 23.0, 24.0, 25.0, 26.0, 27.0, 28.0, 29.0]
    df["rat"] = [25.0, 26.0, 27.0, 28.0, 29.0, 30.0, 31.0, 32.0, 33.0, 34.0]
    df["oat"] = [15.0, 16.0, 17.0, 18.0, 19.0, 20.0, 21.0, 22.0, 23.0, 24.0]
    df["supply_vfd_speed"] = [0.5, 0.5, 0.5, 0.5, 0.5, 0.5, 0.5, 0.5, 0.5, 0.5]

    # Initialize fault condition
    config = {
        "MAT_COL": "mat",
        "RAT_COL": "rat",
        "OAT_COL": "oat",
        "SUPPLY_VFD_SPEED_COL": "supply_vfd_speed",
        "MIX_DEGF_ERR_THRES": 0.5,
        "OUTDOOR_DEGF_ERR_THRES": 0.5,
        "RETURN_DEGF_ERR_THRES": 0.5,
        "TROUBLESHOOT_MODE": False,
        "ROLLING_WINDOW_SIZE": 5
    }
    fault = FaultConditionTwo(config)

    # Apply fault condition
    result = fault.apply(df)

    # Check that fc2_flag column exists and contains only 0s and 1s
    assert "fc2_flag" in result.columns
    assert result["fc2_flag"].isin([0, 1]).all()


def test_fc2_apply_with_fault():
    """Test the apply method with data that should trigger a fault."""
    # Create sample data with conditions that should trigger a fault
    dates = pd.date_range(start="2024-01-01", periods=10, freq="1min")
    df = pd.DataFrame(index=dates)
    df["mat"] = [15.0, 15.0, 15.0, 15.0, 15.0, 15.0, 15.0, 15.0, 15.0, 15.0]  # Low mix temp
    df["rat"] = [25.0, 25.0, 25.0, 25.0, 25.0, 25.0, 25.0, 25.0, 25.0, 25.0]  # High return temp
    df["oat"] = [20.0, 20.0, 20.0, 20.0, 20.0, 20.0, 20.0, 20.0, 20.0, 20.0]  # Moderate outside temp
    df["supply_vfd_speed"] = [0.5, 0.5, 0.5, 0.5, 0.5, 0.5, 0.5, 0.5, 0.5, 0.5]  # Fan running

    # Initialize fault condition
    config = {
        "MAT_COL": "mat",
        "RAT_COL": "rat",
        "OAT_COL": "oat",
        "SUPPLY_VFD_SPEED_COL": "supply_vfd_speed",
        "MIX_DEGF_ERR_THRES": 0.5,
        "OUTDOOR_DEGF_ERR_THRES": 0.5,
        "RETURN_DEGF_ERR_THRES": 0.5,
        "TROUBLESHOOT_MODE": False,
        "ROLLING_WINDOW_SIZE": 5
    }
    fault = FaultConditionTwo(config)

    # Apply fault condition
    result = fault.apply(df)

    # Check that fault is detected (fc2_flag should be 1)
    assert result["fc2_flag"].sum() > 0  # At least one fault should be detected 