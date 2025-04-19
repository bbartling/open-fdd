import pandas as pd
import pytest

from open_fdd.air_handling_unit.faults import FaultConditionEleven
from open_fdd.air_handling_unit.faults.helper_utils import HelperUtils
from open_fdd.core.exceptions import MissingColumnError

"""
To see print statements in pytest run with:
$ py -3.12 -m pytest tests/ahu/test_ahu_fc11.py -rP -s

OAT Temp too low for 100% cooling in OS3
"""

# Constants
TEST_OUTDOOR_DEGF_ERR_THRES = 5.0
TEST_MIX_DEGF_ERR_THRES = 2.0
TEST_OAT_COL = "out_air_temp"
TEST_MAT_COL = "mix_air_temp"
TEST_ECONOMIZER_SIG_COL = "economizer_sig_col"
ROLLING_WINDOW_SIZE = 5

# Initialize FaultConditionEleven with a dictionary
fault_condition_params = {
    "OUTDOOR_DEGF_ERR_THRES": TEST_OUTDOOR_DEGF_ERR_THRES,
    "MIX_DEGF_ERR_THRES": TEST_MIX_DEGF_ERR_THRES,
    "OAT_COL": TEST_OAT_COL,
    "MAT_COL": TEST_MAT_COL,
    "ECONOMIZER_SIG_COL": TEST_ECONOMIZER_SIG_COL,
    "TROUBLESHOOT_MODE": False,
    "ROLLING_WINDOW_SIZE": ROLLING_WINDOW_SIZE,
}

fc11 = FaultConditionEleven(fault_condition_params)


class TestFaultConditionEleven:

    def no_fault_df_no_econ(self) -> pd.DataFrame:
        data = {
            TEST_OAT_COL: [56, 56, 56, 56, 56, 56],
            TEST_MAT_COL: [56, 56, 56, 56, 56, 56],
            TEST_ECONOMIZER_SIG_COL: [0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
        }
        return pd.DataFrame(data)

    def fault_df_in_econ(self) -> pd.DataFrame:
        data = {
            TEST_OAT_COL: [44, 44, 44, 44, 44, 44],
            TEST_MAT_COL: [56, 56, 56, 56, 56, 56],
            TEST_ECONOMIZER_SIG_COL: [1.0, 1.0, 1.0, 1.0, 1.0, 1.0],
        }
        return pd.DataFrame(data)

    def test_no_fault_no_econ(self):
        results = fc11.apply(self.no_fault_df_no_econ())
        actual = results["fc11_flag"].sum()
        expected = 0
        message = (
            f"FC11 no_fault_df_no_econ actual is {actual} and expected is {expected}"
        )
        assert actual == expected, message

    def test_fault_in_econ(self):
        results = fc11.apply(self.fault_df_in_econ())
        actual = results["fc11_flag"].sum()
        expected = 2
        message = f"FC11 fault_df_in_econ actual is {actual} and expected is {expected}"
        assert actual == expected, message


class TestFaultOnInt:

    def fault_df_on_output_int(self) -> pd.DataFrame:
        data = {
            TEST_OAT_COL: [44, 44, 44, 44, 44, 44],
            TEST_MAT_COL: [56, 56, 56, 56, 56, 56],
            TEST_ECONOMIZER_SIG_COL: [1, 1, 1, 1, 1, 1],  # Incorrect type
        }
        return pd.DataFrame(data)

    def test_fault_on_int(self):
        with pytest.raises(
            TypeError,
            match=HelperUtils().float_int_check_err(TEST_ECONOMIZER_SIG_COL),
        ):
            fc11.apply(self.fault_df_on_output_int())


class TestFaultOnFloatGreaterThanOne:

    def fault_df_on_output_greater_than_one(self) -> pd.DataFrame:
        data = {
            TEST_OAT_COL: [44, 44, 44, 44, 44, 44],
            TEST_MAT_COL: [56, 56, 56, 56, 56, 56],
            TEST_ECONOMIZER_SIG_COL: [1.1, 1.2, 1.1, 1.3, 1.1, 1.2],  # Values > 1.0
        }
        return pd.DataFrame(data)

    def test_fault_on_float_greater_than_one(self):
        with pytest.raises(
            TypeError,
            match=HelperUtils().float_max_check_err(TEST_ECONOMIZER_SIG_COL),
        ):
            fc11.apply(self.fault_df_on_output_greater_than_one())


class TestFaultOnMixedTypes:

    def fault_df_on_mixed_types(self) -> pd.DataFrame:
        data = {
            TEST_OAT_COL: [44, 44, 44, 44, 44, 44],
            TEST_MAT_COL: [56, 56, 56, 56, 56, 56],
            TEST_ECONOMIZER_SIG_COL: [1.1, 0.55, 1.2, 1.3, 0.55, 1.1],  # Mixed types
        }
        return pd.DataFrame(data)

    def test_fault_on_mixed_types(self):
        with pytest.raises(
            TypeError,
            match=HelperUtils().float_max_check_err(TEST_ECONOMIZER_SIG_COL),
        ):
            fc11.apply(self.fault_df_on_mixed_types())


if __name__ == "__main__":
    pytest.main()
