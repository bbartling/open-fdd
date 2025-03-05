import pandas as pd
import pytest
from open_fdd.air_handling_unit.faults import FaultConditionSixteen
from open_fdd.core.exceptions import MissingColumnError, InvalidParameterError
from open_fdd.air_handling_unit.faults.helper_utils import HelperUtils

"""
To see print statements in pytest run with:
$ py -3.12 -m pytest open_fdd/tests/ahu/test_ahu_fc16.py -rP -s

ERV effectiveness should be within specified thresholds based on OAT.
"""

# Constants
TEST_ERV_EFFICIENCY_MIN_HEATING = 0.65
TEST_ERV_EFFICIENCY_MAX_HEATING = 0.8
TEST_ERV_EFFICIENCY_MIN_COOLING = 0.45
TEST_ERV_EFFICIENCY_MAX_COOLING = 0.6
TEST_OAT_LOW_THRESHOLD = 32.0
TEST_OAT_HIGH_THRESHOLD = 80.0
TEST_OAT_RAT_DELTA_THRES = 15.0
TEST_MIX_DEGF_ERR_THRES = 2.0
TEST_OUTDOOR_DEGF_ERR_THRES = 5.0
TEST_ERV_OAT_ENTER_COL = "erv_oat_enter"
TEST_ERV_OAT_LEAVING_COL = "erv_oat_leaving"
TEST_ERV_EAT_ENTER_COL = "erv_eat_enter"
TEST_ERV_EAT_LEAVING_COL = "erv_eat_leaving"
TEST_SUPPLY_VFD_SPEED_COL = "supply_vfd_speed"
TEST_OAT_COL = "out_air_temp"
TEST_MAT_COL = "mix_air_temp"
TEST_ECONOMIZER_SIG_COL = "economizer_sig_col"
ROLLING_WINDOW_SIZE = 1

# Initialize FaultConditionSixteen with a dictionary
fault_condition_params = {
    "ERV_EFFICIENCY_MIN_HEATING": TEST_ERV_EFFICIENCY_MIN_HEATING,
    "ERV_EFFICIENCY_MAX_HEATING": TEST_ERV_EFFICIENCY_MAX_HEATING,
    "ERV_EFFICIENCY_MIN_COOLING": TEST_ERV_EFFICIENCY_MIN_COOLING,
    "ERV_EFFICIENCY_MAX_COOLING": TEST_ERV_EFFICIENCY_MAX_COOLING,
    "OAT_LOW_THRESHOLD": TEST_OAT_LOW_THRESHOLD,
    "OAT_HIGH_THRESHOLD": TEST_OAT_HIGH_THRESHOLD,
    "OAT_RAT_DELTA_MIN": TEST_OAT_RAT_DELTA_THRES,
    "MIX_DEGF_ERR_THRES": TEST_MIX_DEGF_ERR_THRES,
    "OUTDOOR_DEGF_ERR_THRES": TEST_OUTDOOR_DEGF_ERR_THRES,
    "ERV_OAT_ENTER_COL": TEST_ERV_OAT_ENTER_COL,
    "ERV_OAT_LEAVING_COL": TEST_ERV_OAT_LEAVING_COL,
    "ERV_EAT_ENTER_COL": TEST_ERV_EAT_ENTER_COL,
    "ERV_EAT_LEAVING_COL": TEST_ERV_EAT_LEAVING_COL,
    "SUPPLY_VFD_SPEED_COL": TEST_SUPPLY_VFD_SPEED_COL,
    "OAT_COL": TEST_OAT_COL,
    "MAT_COL": TEST_MAT_COL,
    "ECONOMIZER_SIG_COL": TEST_ECONOMIZER_SIG_COL,
    "TROUBLESHOOT_MODE": False,
    "ROLLING_WINDOW_SIZE": ROLLING_WINDOW_SIZE,
}

fc16 = FaultConditionSixteen(fault_condition_params)


class TestFaultConditionSixteen:

    def no_fault_htg_df(self) -> pd.DataFrame:
        data = {
            TEST_ERV_OAT_ENTER_COL: [10, 10, 10, 10, 10, 10],
            TEST_ERV_OAT_LEAVING_COL: [50.0, 50.5, 50.8, 50.6, 50.2, 50.4],
            TEST_ERV_EAT_ENTER_COL: [70, 70, 70, 70, 70, 70],
            TEST_ERV_EAT_LEAVING_COL: [60, 60.5, 60.2, 60.4, 60.1, 60.3],
            TEST_SUPPLY_VFD_SPEED_COL: [0.5, 0.6, 0.5, 0.7, 0.5, 0.6],
        }
        return pd.DataFrame(data)

    def fault_htg_df_low_eff(self) -> pd.DataFrame:
        data = {
            TEST_ERV_OAT_ENTER_COL: [10, 10, 10, 10, 10, 10],
            TEST_ERV_OAT_LEAVING_COL: [20.0, 20.5, 20.8, 20.6, 20.2, 20.4],
            TEST_ERV_EAT_ENTER_COL: [70, 70, 70, 70, 70, 70],
            TEST_ERV_EAT_LEAVING_COL: [60, 60.5, 60.2, 60.4, 60.1, 60.3],
            TEST_SUPPLY_VFD_SPEED_COL: [0.5, 0.6, 0.5, 0.7, 0.5, 0.6],
        }
        return pd.DataFrame(data)

    def fault_htg_df_high_eff(self) -> pd.DataFrame:
        data = {
            TEST_ERV_OAT_ENTER_COL: [10, 10, 10, 10, 10, 10],
            TEST_ERV_OAT_LEAVING_COL: [90.0, 90.5, 90.8, 90.6, 90.2, 90.4],
            TEST_ERV_EAT_ENTER_COL: [70, 70, 70, 70, 70, 70],
            TEST_ERV_EAT_LEAVING_COL: [60, 60.5, 60.2, 60.4, 60.1, 60.3],
            TEST_SUPPLY_VFD_SPEED_COL: [0.5, 0.6, 0.5, 0.7, 0.5, 0.6],
        }
        return pd.DataFrame(data)

    def test_no_fault_htg(self):
        results = fc16.apply(self.no_fault_htg_df())
        actual = results["fc16_flag"].sum()
        expected = 0
        message = f"FC16 no_fault_htg actual is {actual} and expected is {expected}"
        assert actual == expected, message

    def test_fault_htg_low_eff(self):
        results = fc16.apply(self.fault_htg_df_low_eff())
        actual = results["fc16_flag"].sum()
        expected = 6
        message = (
            f"FC16 fault_htg_low_eff actual is {actual} and expected is {expected}"
        )
        assert actual == expected, message

    def test_fault_htg_high_eff(self):
        results = fc16.apply(self.fault_htg_df_high_eff())
        actual = results["fc16_flag"].sum()
        expected = 6
        message = (
            f"FC16 fault_htg_high_eff actual is {actual} and expected is {expected}"
        )
        assert actual == expected, message

    def test_fault_with_insufficient_oat_rat_delta(self):
        """Test that no fault is raised when the OAT-RAT delta is below the minimum threshold."""
        data = {
            TEST_ERV_OAT_ENTER_COL: [10, 10, 10, 10, 10, 10],
            TEST_ERV_OAT_LEAVING_COL: [20.0, 20.5, 20.8, 20.6, 20.2, 20.4],
            TEST_ERV_EAT_ENTER_COL: [24, 24, 24, 24, 24, 24],  # Low delta with OAT
            TEST_ERV_EAT_LEAVING_COL: [22, 22.5, 22.2, 22.4, 22.1, 22.3],
            TEST_SUPPLY_VFD_SPEED_COL: [0.5, 0.6, 0.5, 0.7, 0.5, 0.6],
        }
        df = pd.DataFrame(data)
        results = fc16.apply(df)
        actual = results["fc16_flag"].sum()
        expected = 0  # No fault should be triggered due to insufficient delta
        message = f"FC16 fault_with_insufficient_oat_rat_delta actual is {actual} and expected is {expected}"
        assert actual == expected, message


class TestFaultOnInvalidParams:

    def test_invalid_param_type(self):
        """Test that InvalidParameterError is raised for non-float parameters."""
        with pytest.raises(InvalidParameterError) as excinfo:
            FaultConditionSixteen(
                {
                    "ERV_EFFICIENCY_MIN_HEATING": "0.65",  # Invalid, should be float
                    "ERV_EFFICIENCY_MAX_HEATING": 0.8,
                    "ERV_EFFICIENCY_MIN_COOLING": 0.45,
                    "ERV_EFFICIENCY_MAX_COOLING": 0.6,
                    "OAT_LOW_THRESHOLD": 32.0,
                    "OAT_HIGH_THRESHOLD": 80.0,
                    "OAT_RAT_DELTA_MIN": TEST_OAT_RAT_DELTA_THRES,
                    "ERV_OAT_ENTER_COL": TEST_ERV_OAT_ENTER_COL,
                    "ERV_OAT_LEAVING_COL": TEST_ERV_OAT_LEAVING_COL,
                    "ERV_EAT_ENTER_COL": TEST_ERV_EAT_ENTER_COL,
                    "ERV_EAT_LEAVING_COL": TEST_ERV_EAT_LEAVING_COL,
                    "SUPPLY_VFD_SPEED_COL": TEST_SUPPLY_VFD_SPEED_COL,
                }
            )
        assert "should be a float" in str(excinfo.value)

    def test_invalid_efficiency_value(self):
        """Test that InvalidParameterError is raised if efficiency values are out of 0.0 - 1.0 range."""
        with pytest.raises(InvalidParameterError) as excinfo:
            FaultConditionSixteen(
                {
                    "ERV_EFFICIENCY_MIN_HEATING": 75.0,  # Invalid, should be between 0.0 and 1.0
                    "ERV_EFFICIENCY_MAX_HEATING": 0.8,
                    "ERV_EFFICIENCY_MIN_COOLING": 0.45,
                    "ERV_EFFICIENCY_MAX_COOLING": 0.6,
                    "OAT_LOW_THRESHOLD": 32.0,
                    "OAT_HIGH_THRESHOLD": 80.0,
                    "OAT_RAT_DELTA_MIN": TEST_OAT_RAT_DELTA_THRES,
                    "ERV_OAT_ENTER_COL": TEST_ERV_OAT_ENTER_COL,
                    "ERV_OAT_LEAVING_COL": TEST_ERV_OAT_LEAVING_COL,
                    "ERV_EAT_ENTER_COL": TEST_ERV_EAT_ENTER_COL,
                    "ERV_EAT_LEAVING_COL": TEST_ERV_EAT_LEAVING_COL,
                    "SUPPLY_VFD_SPEED_COL": TEST_SUPPLY_VFD_SPEED_COL,
                }
            )
        assert "should be a float between 0.0 and 1.0" in str(excinfo.value)


class TestFaultOnMissingColumns:

    def test_missing_column(self):
        """Test that MissingColumnError is raised if any required column is None or missing."""
        with pytest.raises(MissingColumnError) as excinfo:
            FaultConditionSixteen(
                {
                    "ERV_EFFICIENCY_MIN_HEATING": 0.65,
                    "ERV_EFFICIENCY_MAX_HEATING": 0.8,
                    "ERV_EFFICIENCY_MIN_COOLING": 0.45,
                    "ERV_EFFICIENCY_MAX_COOLING": 0.6,
                    "OAT_LOW_THRESHOLD": 32.0,
                    "OAT_HIGH_THRESHOLD": 80.0,
                    "OAT_RAT_DELTA_MIN": TEST_OAT_RAT_DELTA_THRES,
                    "ERV_OAT_ENTER_COL": TEST_ERV_OAT_ENTER_COL,
                    "ERV_OAT_LEAVING_COL": None,  # Missing column
                    "ERV_EAT_ENTER_COL": TEST_ERV_EAT_ENTER_COL,
                    "ERV_EAT_LEAVING_COL": TEST_ERV_EAT_LEAVING_COL,
                    "SUPPLY_VFD_SPEED_COL": TEST_SUPPLY_VFD_SPEED_COL,
                }
            ).apply(
                pd.DataFrame(
                    {
                        TEST_ERV_OAT_ENTER_COL: [10, 10, 10],
                        TEST_ERV_EAT_ENTER_COL: [70, 70, 70],
                        TEST_ERV_EAT_LEAVING_COL: [60, 60, 60],
                        TEST_SUPPLY_VFD_SPEED_COL: [0.5, 0.5, 0.5],
                    }
                )
            )
        assert "One or more required columns are missing or None" in str(excinfo.value)


if __name__ == "__main__":
    pytest.main()
