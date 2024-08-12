import pandas as pd
import pytest
from open_fdd.air_handling_unit.faults.fault_condition_two import FaultConditionTwo
from open_fdd.air_handling_unit.faults.helper_utils import HelperUtils

"""
To see print statements in pytest run with:
$ py -3.12 -m pytest tests/ahu/test_ahu_fc2.py -rP -s

Mix air temp lower than out temp
"""

TEST_OUTDOOR_DEGF_ERR_THRES = 5.0
TEST_MIX_DEGF_ERR_THRES = 2.0
TEST_RETURN_DEGF_ERR_THRES = 2.0
TEST_MIX_TEMP_COL = "mix_air_temp"
TEST_RETURN_TEMP_COL = "return_air_temp"
TEST_OUT_TEMP_COL = "out_air_temp"
TEST_SUPPLY_VFD_SPEED_COL = "supply_vfd_speed"
TEST_ROLLING_WINDOW_SIZE = 5

# Initialize FaultConditionTwo with a dictionary
fault_condition_params = {
    "MIX_DEGF_ERR_THRES": TEST_MIX_DEGF_ERR_THRES,
    "RETURN_DEGF_ERR_THRES": TEST_RETURN_DEGF_ERR_THRES,
    "OUTDOOR_DEGF_ERR_THRES": TEST_OUTDOOR_DEGF_ERR_THRES,
    "MAT_COL": TEST_MIX_TEMP_COL,
    "RAT_COL": TEST_RETURN_TEMP_COL,
    "OAT_COL": TEST_OUT_TEMP_COL,
    "SUPPLY_VFD_SPEED_COL": TEST_SUPPLY_VFD_SPEED_COL,
    "TROUBLESHOOT_MODE": False,  # default value
    "ROLLING_WINDOW_SIZE": TEST_ROLLING_WINDOW_SIZE,
}

fc2 = FaultConditionTwo(fault_condition_params)


class TestNoFault(object):

    def no_fault_df(self) -> pd.DataFrame:
        data = {
            TEST_MIX_TEMP_COL: [60.0, 62.0, 64.0, 61.0, 63.0, 60.0],
            TEST_RETURN_TEMP_COL: [72.0, 73.0, 74.0, 72.0, 73.0, 72.0],
            TEST_OUT_TEMP_COL: [45.0, 46.0, 47.0, 45.0, 46.0, 45.0],
            TEST_SUPPLY_VFD_SPEED_COL: [0.8, 0.82, 0.85, 0.8, 0.83, 0.8],
        }
        return pd.DataFrame(data)

    def test_no_fault(self):
        results = fc2.apply(self.no_fault_df())
        actual = results["fc2_flag"].sum()
        expected = 0
        message = f"fc2 no_fault_df actual is {actual} and expected is {expected}"
        print(message)
        assert actual == expected, message


class TestFault(object):

    def fault_df(self) -> pd.DataFrame:
        data = {
            TEST_MIX_TEMP_COL: [45.0, 46.0, 45.0, 46.0, 45.0, 45.0],
            TEST_RETURN_TEMP_COL: [72.0, 72.5, 73.0, 72.0, 72.5, 72.0],
            TEST_OUT_TEMP_COL: [60.0, 60.5, 61.0, 60.0, 60.5, 60.0],
            TEST_SUPPLY_VFD_SPEED_COL: [0.8, 0.82, 0.81, 0.8, 0.82, 0.8],
        }
        return pd.DataFrame(data)

    def test_fault(self):
        results = fc2.apply(self.fault_df())
        actual = results["fc2_flag"].sum()
        expected = 2
        message = f"fc2 fault_df actual is {actual} and expected is {expected}"
        print(message)
        assert actual == expected, message


class TestFaultOnInt(object):

    def fault_df_on_output_int(self) -> pd.DataFrame:
        data = {
            TEST_MIX_TEMP_COL: [45.0, 46.0, 45.0, 46.0, 45.0, 45.0],
            TEST_RETURN_TEMP_COL: [72.0, 72.5, 73.0, 72.0, 72.5, 72.0],
            TEST_OUT_TEMP_COL: [60.0, 60.5, 61.0, 60.0, 60.5, 60.0],
            TEST_SUPPLY_VFD_SPEED_COL: [88, 88, 88, 88, 88, 88],
        }
        return pd.DataFrame(data)

    def test_fault_on_int(self):
        with pytest.raises(
            TypeError,
            match=HelperUtils().float_int_check_err(TEST_SUPPLY_VFD_SPEED_COL),
        ):
            fc2.apply(self.fault_df_on_output_int())


class TestFaultOnFloatGreaterThanOne(object):

    def fault_df_on_output_greater_than_one(self) -> pd.DataFrame:
        data = {
            TEST_MIX_TEMP_COL: [45.0, 46.0, 45.0, 46.0, 45.0, 45.0],
            TEST_RETURN_TEMP_COL: [72.0, 72.5, 73.0, 72.0, 72.5, 72.0],
            TEST_OUT_TEMP_COL: [60.0, 60.5, 61.0, 60.0, 60.5, 60.0],
            TEST_SUPPLY_VFD_SPEED_COL: [1.1, 1.2, 1.3, 1.1, 1.2, 1.1],
        }
        return pd.DataFrame(data)

    def test_fault_on_float_greater_than_one(self):
        with pytest.raises(
            TypeError,
            match=HelperUtils().float_max_check_err(TEST_SUPPLY_VFD_SPEED_COL),
        ):
            fc2.apply(self.fault_df_on_output_greater_than_one())


class TestFaultOnMixedTypes(object):

    def fault_df_on_mixed_types(self) -> pd.DataFrame:
        data = {
            TEST_MIX_TEMP_COL: [45.0, 46.0, 45.0, 46.0, 45.0, 45.0],
            TEST_RETURN_TEMP_COL: [72.0, 72.5, 73.0, 72.0, 72.5, 72.0],
            TEST_OUT_TEMP_COL: [60.0, 60.5, 61.0, 60.0, 60.5, 60.0],
            TEST_SUPPLY_VFD_SPEED_COL: [1.1, 0.82, 1.3, 1.1, 0.82, 1.1],
        }
        return pd.DataFrame(data)

    def test_fault_on_mixed_types(self):
        with pytest.raises(
            TypeError,
            match=HelperUtils().float_max_check_err(TEST_SUPPLY_VFD_SPEED_COL),
        ):
            fc2.apply(self.fault_df_on_mixed_types())
