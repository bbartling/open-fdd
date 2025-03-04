import pytest
import pandas as pd
import numpy as np
from open_fdd.air_handling_unit.faults import FaultConditionFour
from open_fdd.core.exceptions import MissingColumnError, InvalidParameterError


def test_fc4_initialization():
    """Test initialization of FaultConditionFour with valid parameters."""
    config = {
        "DELTA_OS_MAX": 5,
        "AHU_MIN_OA_DPR": 0.2,
        "ECONOMIZER_SIG_COL": "economizer_sig",
        "SUPPLY_VFD_SPEED_COL": "supply_vfd_speed",
        "HEATING_SIG_COL": "heating_sig",
        "COOLING_SIG_COL": "cooling_sig",
        "TROUBLESHOOT_MODE": False,
        "ROLLING_WINDOW_SIZE": 60,
    }
    fault = FaultConditionFour(config)
    assert fault.delta_os_max == 5
    assert fault.ahu_min_oa_dpr == 0.2
    assert fault.economizer_sig_col == "economizer_sig"
    assert fault.supply_vfd_speed_col == "supply_vfd_speed"
    assert fault.heating_sig_col == "heating_sig"
    assert fault.cooling_sig_col == "cooling_sig"


def test_fc4_invalid_delta_os_max():
    """Test initialization with invalid delta_os_max type."""
    config = {
        "DELTA_OS_MAX": "5",  # Should be int, not str
        "AHU_MIN_OA_DPR": 0.2,
        "ECONOMIZER_SIG_COL": "economizer_sig",
        "SUPPLY_VFD_SPEED_COL": "supply_vfd_speed",
    }
    with pytest.raises(InvalidParameterError):
        FaultConditionFour(config)


def test_fc4_invalid_ahu_min_oa_dpr():
    """Test initialization with invalid ahu_min_oa_dpr type."""
    config = {
        "DELTA_OS_MAX": 5,
        "AHU_MIN_OA_DPR": "0.2",  # Should be float, not str
        "ECONOMIZER_SIG_COL": "economizer_sig",
        "SUPPLY_VFD_SPEED_COL": "supply_vfd_speed",
    }
    with pytest.raises(InvalidParameterError):
        FaultConditionFour(config)


def test_fc4_missing_required_columns():
    """Test initialization with missing required columns."""
    config = {
        "DELTA_OS_MAX": 5,
        "AHU_MIN_OA_DPR": 0.2,
        "ECONOMIZER_SIG_COL": None,  # Missing required column
        "SUPPLY_VFD_SPEED_COL": "supply_vfd_speed",
    }
    with pytest.raises(MissingColumnError):
        FaultConditionFour(config)


def test_fc4_apply():
    """Test the apply method with sample data."""
    # Create sample data
    dates = pd.date_range(start="2024-01-01", periods=120, freq="1min")
    df = pd.DataFrame(index=dates)
    df["economizer_sig"] = np.random.choice([0, 0.2, 0.5, 0.8], size=120)
    df["supply_vfd_speed"] = np.random.choice([0, 0.3, 0.6, 0.9], size=120)
    df["heating_sig"] = np.random.choice([0, 0.1, 0.2], size=120)
    df["cooling_sig"] = np.random.choice([0, 0.1, 0.2], size=120)

    # Initialize fault condition
    config = {
        "DELTA_OS_MAX": 5,
        "AHU_MIN_OA_DPR": 0.2,
        "ECONOMIZER_SIG_COL": "economizer_sig",
        "SUPPLY_VFD_SPEED_COL": "supply_vfd_speed",
        "HEATING_SIG_COL": "heating_sig",
        "COOLING_SIG_COL": "cooling_sig",
        "TROUBLESHOOT_MODE": False,
        "ROLLING_WINDOW_SIZE": 60,
    }
    fault = FaultConditionFour(config)

    # Apply fault condition
    result = fault.apply(df)

    # Check that fc4_flag column exists and contains only 0s and 1s
    assert "fc4_flag" in result.columns
    assert result["fc4_flag"].isin([0, 1]).all()
