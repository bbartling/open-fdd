import pytest
import pandas as pd
import numpy as np
from open_fdd.air_handling_unit.faults import FaultConditionSix
from open_fdd.core.exceptions import MissingColumnError, InvalidParameterError


def test_fc6_initialization():
    """Test initialization of FaultConditionSix with valid parameters."""
    config = {
        "SUPPLY_FAN_AIR_VOLUME_COL": "supply_fan_air_volume",
        "MAT_COL": "mat",
        "OAT_COL": "oat",
        "RAT_COL": "rat",
        "SUPPLY_VFD_SPEED_COL": "supply_vfd_speed",
        "ECONOMIZER_SIG_COL": "economizer_sig",
        "HEATING_SIG_COL": "heating_sig",
        "COOLING_SIG_COL": "cooling_sig",
        "AIRFLOW_ERR_THRES": 0.1,
        "AHU_MIN_OA_CFM_DESIGN": 1000.0,
        "OUTDOOR_DEGF_ERR_THRES": 0.5,
        "RETURN_DEGF_ERR_THRES": 0.5,
        "OAT_RAT_DELTA_MIN": 5.0,
        "AHU_MIN_OA_DPR": 0.2,
        "TROUBLESHOOT_MODE": False,
        "ROLLING_WINDOW_SIZE": 5
    }
    fault = FaultConditionSix(config)
    
    # Check base attributes
    assert fault.troubleshoot_mode is False
    assert fault.rolling_window_size == 5
    
    # Check specific attributes
    assert fault.supply_fan_air_volume_col == "supply_fan_air_volume"
    assert fault.mat_col == "mat"
    assert fault.oat_col == "oat"
    assert fault.rat_col == "rat"
    assert fault.supply_vfd_speed_col == "supply_vfd_speed"
    assert fault.economizer_sig_col == "economizer_sig"
    assert fault.heating_sig_col == "heating_sig"
    assert fault.cooling_sig_col == "cooling_sig"
    assert fault.airflow_err_thres == 0.1
    assert fault.ahu_min_oa_cfm_design == 1000.0
    assert fault.outdoor_degf_err_thres == 0.5
    assert fault.return_degf_err_thres == 0.5
    assert fault.oat_rat_delta_min == 5.0
    assert fault.ahu_min_oa_dpr == 0.2


def test_fc6_missing_required_columns():
    """Test initialization with missing required columns."""
    config = {
        "SUPPLY_FAN_AIR_VOLUME_COL": None,  # Missing required column
        "MAT_COL": "mat",
        "OAT_COL": "oat",
        "RAT_COL": "rat",
        "SUPPLY_VFD_SPEED_COL": "supply_vfd_speed",
        "ECONOMIZER_SIG_COL": "economizer_sig",
        "HEATING_SIG_COL": "heating_sig",
        "COOLING_SIG_COL": "cooling_sig",
        "AIRFLOW_ERR_THRES": 0.1,
        "AHU_MIN_OA_CFM_DESIGN": 1000.0,
        "OUTDOOR_DEGF_ERR_THRES": 0.5,
        "RETURN_DEGF_ERR_THRES": 0.5,
        "OAT_RAT_DELTA_MIN": 5.0,
        "AHU_MIN_OA_DPR": 0.2
    }
    with pytest.raises(MissingColumnError):
        FaultConditionSix(config)


def test_fc6_invalid_ahu_min_oa_cfm_design():
    """Test initialization with invalid AHU_MIN_OA_CFM_DESIGN parameter."""
    config = {
        "SUPPLY_FAN_AIR_VOLUME_COL": "supply_fan_air_volume",
        "MAT_COL": "mat",
        "OAT_COL": "oat",
        "RAT_COL": "rat",
        "SUPPLY_VFD_SPEED_COL": "supply_vfd_speed",
        "ECONOMIZER_SIG_COL": "economizer_sig",
        "HEATING_SIG_COL": "heating_sig",
        "COOLING_SIG_COL": "cooling_sig",
        "AIRFLOW_ERR_THRES": 0.1,
        "AHU_MIN_OA_CFM_DESIGN": "invalid",  # Should be float
        "OUTDOOR_DEGF_ERR_THRES": 0.5,
        "RETURN_DEGF_ERR_THRES": 0.5,
        "OAT_RAT_DELTA_MIN": 5.0,
        "AHU_MIN_OA_DPR": 0.2
    }
    with pytest.raises(InvalidParameterError):
        FaultConditionSix(config)


def test_fc6_apply():
    """Test the apply method with sample data."""
    # Create sample data
    dates = pd.date_range(start="2024-01-01", periods=10, freq="1min")
    df = pd.DataFrame(index=dates)
    df["supply_fan_air_volume"] = [2000.0, 2000.0, 2000.0, 2000.0, 2000.0, 2000.0, 2000.0, 2000.0, 2000.0, 2000.0]
    df["mat"] = [20.0, 20.0, 20.0, 20.0, 20.0, 20.0, 20.0, 20.0, 20.0, 20.0]
    df["oat"] = [15.0, 15.0, 15.0, 15.0, 15.0, 15.0, 15.0, 15.0, 15.0, 15.0]
    df["rat"] = [25.0, 25.0, 25.0, 25.0, 25.0, 25.0, 25.0, 25.0, 25.0, 25.0]
    df["supply_vfd_speed"] = [0.5, 0.5, 0.5, 0.5, 0.5, 0.5, 0.5, 0.5, 0.5, 0.5]
    df["economizer_sig"] = [0.2, 0.2, 0.2, 0.2, 0.2, 0.2, 0.2, 0.2, 0.2, 0.2]
    df["heating_sig"] = [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
    df["cooling_sig"] = [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]

    # Initialize fault condition
    config = {
        "SUPPLY_FAN_AIR_VOLUME_COL": "supply_fan_air_volume",
        "MAT_COL": "mat",
        "OAT_COL": "oat",
        "RAT_COL": "rat",
        "SUPPLY_VFD_SPEED_COL": "supply_vfd_speed",
        "ECONOMIZER_SIG_COL": "economizer_sig",
        "HEATING_SIG_COL": "heating_sig",
        "COOLING_SIG_COL": "cooling_sig",
        "AIRFLOW_ERR_THRES": 0.1,
        "AHU_MIN_OA_CFM_DESIGN": 1000.0,
        "OUTDOOR_DEGF_ERR_THRES": 0.5,
        "RETURN_DEGF_ERR_THRES": 0.5,
        "OAT_RAT_DELTA_MIN": 5.0,
        "AHU_MIN_OA_DPR": 0.2,
        "TROUBLESHOOT_MODE": False,
        "ROLLING_WINDOW_SIZE": 5
    }
    fault = FaultConditionSix(config)

    # Apply fault condition
    result = fault.apply(df)

    # Check that fc6_flag column exists and contains only 0s and 1s
    assert "fc6_flag" in result.columns
    assert result["fc6_flag"].isin([0, 1]).all()


def test_fc6_apply_with_fault():
    """Test the apply method with data that should trigger a fault."""
    # Create sample data with conditions that should trigger a fault
    dates = pd.date_range(start="2024-01-01", periods=10, freq="1min")
    df = pd.DataFrame(index=dates)
    df["supply_fan_air_volume"] = [500.0, 500.0, 500.0, 500.0, 500.0, 500.0, 500.0, 500.0, 500.0, 500.0]  # Low airflow
    df["mat"] = [20.0, 20.0, 20.0, 20.0, 20.0, 20.0, 20.0, 20.0, 20.0, 20.0]
    df["oat"] = [15.0, 15.0, 15.0, 15.0, 15.0, 15.0, 15.0, 15.0, 15.0, 15.0]
    df["rat"] = [25.0, 25.0, 25.0, 25.0, 25.0, 25.0, 25.0, 25.0, 25.0, 25.0]
    df["supply_vfd_speed"] = [0.5, 0.5, 0.5, 0.5, 0.5, 0.5, 0.5, 0.5, 0.5, 0.5]
    df["economizer_sig"] = [0.2, 0.2, 0.2, 0.2, 0.2, 0.2, 0.2, 0.2, 0.2, 0.2]
    df["heating_sig"] = [0.1, 0.1, 0.1, 0.1, 0.1, 0.1, 0.1, 0.1, 0.1, 0.1]  # Set to > 0.0 to trigger OS1
    df["cooling_sig"] = [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]

    # Initialize fault condition
    config = {
        "SUPPLY_FAN_AIR_VOLUME_COL": "supply_fan_air_volume",
        "MAT_COL": "mat",
        "OAT_COL": "oat",
        "RAT_COL": "rat",
        "SUPPLY_VFD_SPEED_COL": "supply_vfd_speed",
        "ECONOMIZER_SIG_COL": "economizer_sig",
        "HEATING_SIG_COL": "heating_sig",
        "COOLING_SIG_COL": "cooling_sig",
        "AIRFLOW_ERR_THRES": 0.1,
        "AHU_MIN_OA_CFM_DESIGN": 1000.0,
        "OUTDOOR_DEGF_ERR_THRES": 0.5,
        "RETURN_DEGF_ERR_THRES": 0.5,
        "OAT_RAT_DELTA_MIN": 5.0,
        "AHU_MIN_OA_DPR": 0.2,
        "TROUBLESHOOT_MODE": False,
        "ROLLING_WINDOW_SIZE": 5
    }
    fault = FaultConditionSix(config)

    # Apply fault condition
    result = fault.apply(df)

    # Check that fault is detected (fc6_flag should be 1)
    assert result["fc6_flag"].sum() > 0  # At least one fault should be detected 


def test_fc6_apply_with_fault_cooling_mode():
    """Test the apply method with data that should trigger a fault in cooling mode (OS4)."""
    # Create sample data with conditions that should trigger a fault in cooling mode
    dates = pd.date_range(start="2024-01-01", periods=10, freq="1min")
    df = pd.DataFrame(index=dates)
    df["supply_fan_air_volume"] = [500.0, 500.0, 500.0, 500.0, 500.0, 500.0, 500.0, 500.0, 500.0, 500.0]  # Low airflow
    df["mat"] = [20.0, 20.0, 20.0, 20.0, 20.0, 20.0, 20.0, 20.0, 20.0, 20.0]
    df["oat"] = [15.0, 15.0, 15.0, 15.0, 15.0, 15.0, 15.0, 15.0, 15.0, 15.0]
    df["rat"] = [25.0, 25.0, 25.0, 25.0, 25.0, 25.0, 25.0, 25.0, 25.0, 25.0]
    df["supply_vfd_speed"] = [0.5, 0.5, 0.5, 0.5, 0.5, 0.5, 0.5, 0.5, 0.5, 0.5]
    df["economizer_sig"] = [0.2, 0.2, 0.2, 0.2, 0.2, 0.2, 0.2, 0.2, 0.2, 0.2]  # Equal to AHU_MIN_OA_DPR
    df["heating_sig"] = [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]  # No heating
    df["cooling_sig"] = [0.1, 0.1, 0.1, 0.1, 0.1, 0.1, 0.1, 0.1, 0.1, 0.1]  # Cooling active

    # Initialize fault condition
    config = {
        "SUPPLY_FAN_AIR_VOLUME_COL": "supply_fan_air_volume",
        "MAT_COL": "mat",
        "OAT_COL": "oat",
        "RAT_COL": "rat",
        "SUPPLY_VFD_SPEED_COL": "supply_vfd_speed",
        "ECONOMIZER_SIG_COL": "economizer_sig",
        "HEATING_SIG_COL": "heating_sig",
        "COOLING_SIG_COL": "cooling_sig",
        "AIRFLOW_ERR_THRES": 0.1,
        "AHU_MIN_OA_CFM_DESIGN": 1000.0,
        "OUTDOOR_DEGF_ERR_THRES": 0.5,
        "RETURN_DEGF_ERR_THRES": 0.5,
        "OAT_RAT_DELTA_MIN": 5.0,
        "AHU_MIN_OA_DPR": 0.2,
        "TROUBLESHOOT_MODE": False,
        "ROLLING_WINDOW_SIZE": 5
    }
    fault = FaultConditionSix(config)

    # Apply fault condition
    result = fault.apply(df)

    # Check that fault is detected (fc6_flag should be 1)
    assert result["fc6_flag"].sum() > 0  # At least one fault should be detected 