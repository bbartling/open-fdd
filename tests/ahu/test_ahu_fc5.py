import numpy as np
import pandas as pd
import pytest

from open_fdd.air_handling_unit.faults import FaultConditionFive
from open_fdd.core.exceptions import InvalidParameterError, MissingColumnError


def test_fc5_initialization():
    """Test initialization of FaultConditionFive with valid parameters."""
    config = {
        "MAT_COL": "mat",
        "SAT_COL": "sat",
        "HEATING_SIG_COL": "heating_sig",
        "SUPPLY_VFD_SPEED_COL": "supply_vfd_speed",
        "MIX_DEGF_ERR_THRES": 0.5,
        "SUPPLY_DEGF_ERR_THRES": 0.5,
        "DELTA_T_SUPPLY_FAN": 1.0,
        "TROUBLESHOOT_MODE": False,
        "ROLLING_WINDOW_SIZE": 5,
    }
    fault = FaultConditionFive(config)

    # Check base attributes
    assert fault.troubleshoot_mode is False
    assert fault.rolling_window_size == 5

    # Check specific attributes
    assert fault.mat_col == "mat"
    assert fault.sat_col == "sat"
    assert fault.heating_sig_col == "heating_sig"
    assert fault.supply_vfd_speed_col == "supply_vfd_speed"
    assert fault.mix_degf_err_thres == 0.5
    assert fault.supply_degf_err_thres == 0.5
    assert fault.delta_t_supply_fan == 1.0


def test_fc5_missing_required_columns():
    """Test initialization with missing required columns."""
    config = {
        "MAT_COL": None,  # Missing required column
        "SAT_COL": "sat",
        "HEATING_SIG_COL": "heating_sig",
        "SUPPLY_VFD_SPEED_COL": "supply_vfd_speed",
        "MIX_DEGF_ERR_THRES": 0.5,
        "SUPPLY_DEGF_ERR_THRES": 0.5,
        "DELTA_T_SUPPLY_FAN": 1.0,
    }
    with pytest.raises(MissingColumnError):
        FaultConditionFive(config)


def test_fc5_invalid_threshold():
    """Test initialization with invalid threshold parameters."""
    config = {
        "MAT_COL": "mat",
        "SAT_COL": "sat",
        "HEATING_SIG_COL": "heating_sig",
        "SUPPLY_VFD_SPEED_COL": "supply_vfd_speed",
        "MIX_DEGF_ERR_THRES": "invalid",  # Should be float
        "SUPPLY_DEGF_ERR_THRES": 0.5,
        "DELTA_T_SUPPLY_FAN": 1.0,
    }
    with pytest.raises(InvalidParameterError):
        FaultConditionFive(config)


def test_fc5_apply():
    """Test the apply method with sample data."""
    # Create sample data
    dates = pd.date_range(start="2024-01-01", periods=10, freq="1min")
    df = pd.DataFrame(index=dates)
    df["mat"] = [20.0, 21.0, 22.0, 23.0, 24.0, 25.0, 26.0, 27.0, 28.0, 29.0]
    df["sat"] = [25.0, 26.0, 27.0, 28.0, 29.0, 30.0, 31.0, 32.0, 33.0, 34.0]
    df["heating_sig"] = [0.5, 0.5, 0.5, 0.5, 0.5, 0.5, 0.5, 0.5, 0.5, 0.5]
    df["supply_vfd_speed"] = [0.5, 0.5, 0.5, 0.5, 0.5, 0.5, 0.5, 0.5, 0.5, 0.5]

    # Initialize fault condition
    config = {
        "MAT_COL": "mat",
        "SAT_COL": "sat",
        "HEATING_SIG_COL": "heating_sig",
        "SUPPLY_VFD_SPEED_COL": "supply_vfd_speed",
        "MIX_DEGF_ERR_THRES": 0.5,
        "SUPPLY_DEGF_ERR_THRES": 0.5,
        "DELTA_T_SUPPLY_FAN": 1.0,
        "TROUBLESHOOT_MODE": False,
        "ROLLING_WINDOW_SIZE": 5,
    }
    fault = FaultConditionFive(config)

    # Apply fault condition
    result = fault.apply(df)

    # Check that fc5_flag column exists and contains only 0s and 1s
    assert "fc5_flag" in result.columns
    assert result["fc5_flag"].isin([0, 1]).all()


def test_fc5_apply_with_fault():
    """Test the apply method with data that should trigger a fault."""
    # Create sample data with conditions that should trigger a fault
    dates = pd.date_range(start="2024-01-01", periods=10, freq="1min")
    df = pd.DataFrame(index=dates)
    df["mat"] = [
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
    ]  # High mix temp
    df["sat"] = [
        24.0,
        24.0,
        24.0,
        24.0,
        24.0,
        24.0,
        24.0,
        24.0,
        24.0,
        24.0,
    ]  # Low supply temp
    df["heating_sig"] = [
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
    ]  # Full heating
    df["supply_vfd_speed"] = [
        0.5,
        0.5,
        0.5,
        0.5,
        0.5,
        0.5,
        0.5,
        0.5,
        0.5,
        0.5,
    ]  # Fan running

    # Initialize fault condition
    config = {
        "MAT_COL": "mat",
        "SAT_COL": "sat",
        "HEATING_SIG_COL": "heating_sig",
        "SUPPLY_VFD_SPEED_COL": "supply_vfd_speed",
        "MIX_DEGF_ERR_THRES": 0.5,
        "SUPPLY_DEGF_ERR_THRES": 0.5,
        "DELTA_T_SUPPLY_FAN": 1.0,
        "TROUBLESHOOT_MODE": False,
        "ROLLING_WINDOW_SIZE": 5,
    }
    fault = FaultConditionFive(config)

    # Apply fault condition
    result = fault.apply(df)

    # Check that fault is detected (fc5_flag should be 1)
    assert result["fc5_flag"].sum() > 0  # At least one fault should be detected
