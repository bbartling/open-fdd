import pandas as pd
import pytest

from open_fdd.air_handling_unit.faults import FaultConditionEight
from open_fdd.air_handling_unit.faults.helper_utils import HelperUtils

"""
To see print statements in pytest run with:
$ py -3.12 -m pytest tests/ahu/test_ahu_fc8.py -rP -s

Supply air temperature approx equal mix temp in full econ.
"""

# Constants
TEST_DELTA_T_SUPPLY_FAN = 2.0
TEST_MIX_DEGF_ERR_THRES = 2.0
TEST_SUPPLY_DEGF_ERR_THRES = 2.0
TEST_AHU_MIN_OA_DPR = 0.2
TEST_MAT_COL = "mix_air_temp"
TEST_SAT_COL = "supply_air_temp"
TEST_ECONOMIZER_SIG_COL = "economizer_sig"
TEST_COOLING_SIG_COL = "cooling_sig"
ROLLING_WINDOW_SIZE = 5

# Initialize FaultConditionEight with a dictionary
fault_condition_params = {
    "DELTA_T_SUPPLY_FAN": TEST_DELTA_T_SUPPLY_FAN,
    "MIX_DEGF_ERR_THRES": TEST_MIX_DEGF_ERR_THRES,
    "SUPPLY_DEGF_ERR_THRES": TEST_SUPPLY_DEGF_ERR_THRES,
    "AHU_MIN_OA_DPR": TEST_AHU_MIN_OA_DPR,
    "MAT_COL": TEST_MAT_COL,
    "SAT_COL": TEST_SAT_COL,
    "ECONOMIZER_SIG_COL": TEST_ECONOMIZER_SIG_COL,
    "COOLING_SIG_COL": TEST_COOLING_SIG_COL,
    "TROUBLESHOOT_MODE": False,
    "ROLLING_WINDOW_SIZE": ROLLING_WINDOW_SIZE,
}

fc8 = FaultConditionEight(fault_condition_params)


class TestFaultConditionEight:

    def fault_df(self) -> pd.DataFrame:
        data = {
            TEST_MAT_COL: [50, 50.5, 50.5, 50.8, 50.2, 50.6],
            TEST_SAT_COL: [40, 39.5, 39.8, 39.6, 39.2, 39.4],
            TEST_ECONOMIZER_SIG_COL: [0.5, 0.6, 0.5, 0.7, 0.5, 0.6],
            TEST_COOLING_SIG_COL: [0.05, 0.04, 0.03, 0.02, 0.01, 0.0],
        }
        return pd.DataFrame(data)

    def no_fault_df(self) -> pd.DataFrame:
        data = {
            TEST_MAT_COL: [50, 50.5, 50.5, 50.8, 50.2, 50.6],
            TEST_SAT_COL: [51, 51.5, 50.9, 51.8, 51.2, 51.6],
            TEST_ECONOMIZER_SIG_COL: [0.5, 0.6, 0.5, 0.7, 0.5, 0.6],
            TEST_COOLING_SIG_COL: [0.05, 0.04, 0.03, 0.02, 0.01, 0.0],
        }
        return pd.DataFrame(data)

    def test_fault_condition_eight(self):
        results = fc8.apply(self.fault_df())
        actual = results["fc8_flag"].sum()
        expected = 2
        message = f"FC8 fault_df actual is {actual} and expected is {expected}"
        assert actual == expected, message

    def test_no_fault_condition_eight(self):
        results = fc8.apply(self.no_fault_df())
        actual = results["fc8_flag"].sum()
        expected = 0
        message = f"FC8 no_fault_df actual is {actual} and expected is {expected}"
        assert actual == expected, message


class TestFaultOnInt:

    def fault_df_on_output_int(self) -> pd.DataFrame:
        data = {
            TEST_MAT_COL: [50, 50.5, 50.5, 50.8, 50.2, 50.6],
            TEST_SAT_COL: [40, 39.5, 39.8, 39.6, 39.2, 39.4],
            TEST_ECONOMIZER_SIG_COL: [0.5, 0.6, 0.5, 0.7, 0.5, 0.6],
            TEST_COOLING_SIG_COL: [55, 56, 54, 55, 57, 55],  # Incorrect type
        }
        return pd.DataFrame(data)

    def test_fault_on_int(self):
        with pytest.raises(
            TypeError, match=HelperUtils().float_int_check_err(TEST_COOLING_SIG_COL)
        ):
            fc8.apply(self.fault_df_on_output_int())


class TestFaultOnFloatGreaterThanOne:

    def fault_df_on_output_greater_than_one(self) -> pd.DataFrame:
        data = {
            TEST_MAT_COL: [50, 50.5, 50.5, 50.8, 50.2, 50.6],
            TEST_SAT_COL: [40, 39.5, 39.8, 39.6, 39.2, 39.4],
            TEST_ECONOMIZER_SIG_COL: [0.5, 0.6, 0.5, 0.7, 0.5, 0.6],
            TEST_COOLING_SIG_COL: [1.1, 1.2, 1.1, 1.3, 1.1, 1.2],  # Values > 1.0
        }
        return pd.DataFrame(data)

    def test_fault_on_float_greater_than_one(self):
        with pytest.raises(
            TypeError, match=HelperUtils().float_max_check_err(TEST_COOLING_SIG_COL)
        ):
            fc8.apply(self.fault_df_on_output_greater_than_one())


class TestFaultOnMixedTypes:

    def fault_df_on_mixed_types(self) -> pd.DataFrame:
        data = {
            TEST_MAT_COL: [50, 50.5, 50.5, 50.8, 50.2, 50.6],
            TEST_SAT_COL: [40, 39.5, 39.8, 39.6, 39.2, 39.4],
            TEST_ECONOMIZER_SIG_COL: [0.5, 0.6, 0.5, 0.7, 0.5, 0.6],
            TEST_COOLING_SIG_COL: [1.1, 0.55, 1.2, 1.3, 0.55, 1.1],  # Mixed types
        }
        return pd.DataFrame(data)

    def test_fault_on_mixed_types(self):
        with pytest.raises(
            TypeError, match=HelperUtils().float_max_check_err(TEST_COOLING_SIG_COL)
        ):
            fc8.apply(self.fault_df_on_mixed_types())


if __name__ == "__main__":
    pytest.main()
