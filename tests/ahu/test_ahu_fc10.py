import pytest
import pandas as pd
import numpy as np
from open_fdd.air_handling_unit.faults import FaultConditionTen
from open_fdd.core.exceptions import MissingColumnError, InvalidParameterError

def test_fault_condition_ten_initialization():
    """Test initialization of FaultConditionTen with valid parameters."""
    config = {
        "TROUBLESHOOT_MODE": False,
        "ROLLING_WINDOW_SIZE": 5,
        "OUTDOOR_DEGF_ERR_THRES": 0.5,
        "MIX_DEGF_ERR_THRES": 0.5,
        "OAT_COL": "oat",
        "MAT_COL": "mat",
        "COOLING_SIG_COL": "cooling",
        "ECONOMIZER_SIG_COL": "economizer"
    }
    
    fault = FaultConditionTen(config)
    
    # Check base attributes
    assert fault.troubleshoot_mode is False
    assert fault.rolling_window_size == 5
    
    # Check specific attributes
    assert fault.outdoor_degf_err_thres == 0.5
    assert fault.mix_degf_err_thres == 0.5
    assert fault.oat_col == "oat"
    assert fault.mat_col == "mat"
    assert fault.cooling_sig_col == "cooling"
    assert fault.economizer_sig_col == "economizer"

def test_fault_condition_ten_invalid_threshold():
    """Test initialization with invalid threshold parameters."""
    config = {
        "OUTDOOR_DEGF_ERR_THRES": "invalid",
        "MIX_DEGF_ERR_THRES": 0.5,
        "OAT_COL": "oat",
        "MAT_COL": "mat",
        "COOLING_SIG_COL": "cooling",
        "ECONOMIZER_SIG_COL": "economizer"
    }
    
    with pytest.raises(InvalidParameterError):
        FaultConditionTen(config)

def test_fault_condition_ten_missing_columns():
    """Test initialization with missing required columns."""
    config = {
        "OUTDOOR_DEGF_ERR_THRES": 0.5,
        "MIX_DEGF_ERR_THRES": 0.5,
        "OAT_COL": None,
        "MAT_COL": "mat",
        "COOLING_SIG_COL": "cooling",
        "ECONOMIZER_SIG_COL": "economizer"
    }
    
    with pytest.raises(MissingColumnError):
        FaultConditionTen(config)

def test_fault_condition_ten_apply():
    """Test applying the fault condition to a DataFrame."""
    # Create test data
    data = {
        "oat": [20.0, 21.0, 22.0, 23.0, 24.0],
        "mat": [20.0, 21.0, 22.0, 23.0, 24.0],
        "cooling": [1.0, 1.0, 1.0, 1.0, 1.0],
        "economizer": [1.0, 1.0, 1.0, 1.0, 1.0]
    }
    df = pd.DataFrame(data)
    
    config = {
        "TROUBLESHOOT_MODE": False,
        "ROLLING_WINDOW_SIZE": 3,
        "OUTDOOR_DEGF_ERR_THRES": 0.5,
        "MIX_DEGF_ERR_THRES": 0.5,
        "OAT_COL": "oat",
        "MAT_COL": "mat",
        "COOLING_SIG_COL": "cooling",
        "ECONOMIZER_SIG_COL": "economizer"
    }
    
    fault = FaultConditionTen(config)
    result = fault.apply(df)
    
    # Check that fc10_flag column was added
    assert "fc10_flag" in result.columns
    # Check that all flags are 0 since temperature difference is 0
    assert result["fc10_flag"].sum() == 0

def test_fault_condition_ten_apply_with_fault():
    """Test applying the fault condition with a temperature difference that exceeds threshold."""
    # Create test data with temperature difference exceeding threshold
    data = {
        "oat": [20.0, 21.0, 22.0, 23.0, 24.0],
        "mat": [25.0, 26.0, 27.0, 28.0, 29.0],  # 5°F difference
        "cooling": [1.0, 1.0, 1.0, 1.0, 1.0],
        "economizer": [1.0, 1.0, 1.0, 1.0, 1.0]
    }
    df = pd.DataFrame(data)
    
    config = {
        "TROUBLESHOOT_MODE": False,
        "ROLLING_WINDOW_SIZE": 3,
        "OUTDOOR_DEGF_ERR_THRES": 0.5,
        "MIX_DEGF_ERR_THRES": 0.5,
        "OAT_COL": "oat",
        "MAT_COL": "mat",
        "COOLING_SIG_COL": "cooling",
        "ECONOMIZER_SIG_COL": "economizer"
    }
    
    fault = FaultConditionTen(config)
    result = fault.apply(df)
    
    # Check that fc10_flag column was added
    assert "fc10_flag" in result.columns
    # Check that flags are 1 after rolling window
    assert result["fc10_flag"].sum() == 3  # Last 3 rows should have flag=1 