import pandas as pd
import pytest
from open_fdd.air_handling_unit.faults import FaultConditionFive
from open_fdd.air_handling_unit.faults.helper_utils import HelperUtils

"""
To see print statements in pytest run with:
$ py -3.12 -m pytest open_fdd/tests/ahu/test_ahu_fc5.py -rP -s

SAT too low; should be higher than MAT in HTG MODE
"""

# Constants
TEST_MIX_DEGF_ERR_THRES = 2.0
TEST_SUPPLY_DEGF_ERR_THRES = 2.0
TEST_DELTA_T_SUPPLY_FAN = 5.0
TEST_MIX_TEMP_COL = "mix_air_temp"
TEST_SUPPLY_TEMP_COL = "supply_air_temp"
TEST_HEATING_COIL_SIG_COL = "heating_sig_col"
TEST_SUPPLY_VFD_SPEED_COL = "supply_vfd_speed"
ROLLING_WINDOW_SIZE = 5

# Initialize FaultConditionFive with a dictionary
fault_condition_params = {
    "MIX_DEGF_ERR_THRES": TEST_MIX_DEGF_ERR_THRES,
    "SUPPLY_DEGF_ERR_THRES": TEST_SUPPLY_DEGF_ERR_THRES,
    "DELTA_T_SUPPLY_FAN": TEST_DELTA_T_SUPPLY_FAN,
    "MAT_COL": TEST_MIX_TEMP_COL,
    "SAT_COL": TEST_SUPPLY_TEMP_COL,
    "HEATING_SIG_COL": TEST_HEATING_COIL_SIG_COL,
    "SUPPLY_VFD_SPEED_COL": TEST_SUPPLY_VFD_SPEED_COL,
    "TROUBLESHOOT_MODE": False,  # default value
    "ROLLING_WINDOW_SIZE": ROLLING_WINDOW_SIZE,  # rolling sum window size
}

fc5 = FaultConditionFive(fault_condition_params)


class TestNoFaultInHtg(object):

    def no_fault_df_in_htg(self) -> pd.DataFrame:
        data = {
            TEST_MIX_TEMP_COL: [40.0, 42.0, 43.0, 41.0, 39.0, 40.0],
            TEST_SUPPLY_TEMP_COL: [80.0, 82.0, 81.0, 83.0, 84.0, 80.0],
            TEST_HEATING_COIL_SIG_COL: [0.55, 0.56, 0.54, 0.55, 0.57, 0.55],
            TEST_SUPPLY_VFD_SPEED_COL: [0.55, 0.56, 0.54, 0.55, 0.57, 0.55],
        }
        return pd.DataFrame(data)

    def test_no_fault_in_htg(self):
        results = fc5.apply(self.no_fault_df_in_htg())
        actual = results["fc5_flag"].sum()
        expected = 0
        message = (
            f"FC5 no_fault_df_in_htg actual is {actual} and expected is {expected}"
        )
        assert actual == expected, message


class TestFaultInHtg(object):

    def fault_df_in_htg(self) -> pd.DataFrame:
        data = {
            TEST_MIX_TEMP_COL: [80.0, 81.0, 79.0, 80.5, 82.0, 80.0],
            TEST_SUPPLY_TEMP_COL: [
                81.0,
                81.0,
                79.0,
                80.5,
                82.0,
                80.0,
            ],  # sim not temp rise
            TEST_HEATING_COIL_SIG_COL: [0.55, 0.56, 0.54, 0.55, 0.57, 0.55],
            TEST_SUPPLY_VFD_SPEED_COL: [0.55, 0.56, 0.54, 0.55, 0.57, 0.55],
        }
        return pd.DataFrame(data)

    def test_fault_in_htg(self):
        results = fc5.apply(self.fault_df_in_htg())
        actual = results["fc5_flag"].sum()
        expected = 2
        message = f"FC5 fault_df_in_htg actual is {actual} and expected is {expected}"
        assert actual == expected, message


class TestNoFaultNoHtg(object):

    def no_fault_df_no_htg(self) -> pd.DataFrame:
        data = {
            TEST_MIX_TEMP_COL: [40.0, 42.0, 43.0, 41.0, 39.0, 40.0],
            TEST_SUPPLY_TEMP_COL: [80.0, 82.0, 81.0, 83.0, 84.0, 80.0],
            TEST_HEATING_COIL_SIG_COL: [0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
            TEST_SUPPLY_VFD_SPEED_COL: [0.55, 0.56, 0.54, 0.55, 0.57, 0.55],
        }
        return pd.DataFrame(data)

    def test_no_fault_no_htg(self):
        results = fc5.apply(self.no_fault_df_no_htg())
        actual = results["fc5_flag"].sum()
        expected = 0
        message = (
            f"FC5 no_fault_df_no_htg actual is {actual} and expected is {expected}"
        )
        assert actual == expected, message


class TestFaultNoHtg(object):

    def fault_df_no_htg(self) -> pd.DataFrame:
        data = {
            TEST_MIX_TEMP_COL: [80.0, 81.0, 79.0, 80.5, 82.0, 80.0],
            TEST_SUPPLY_TEMP_COL: [40.0, 41.0, 42.0, 43.0, 40.5, 40.0],
            TEST_HEATING_COIL_SIG_COL: [0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
            TEST_SUPPLY_VFD_SPEED_COL: [0.55, 0.56, 0.54, 0.55, 0.57, 0.55],
        }
        return pd.DataFrame(data)

    def test_fault_no_htg(self):
        results = fc5.apply(self.fault_df_no_htg())
        actual = results["fc5_flag"].sum()
        expected = 0
        message = f"FC5 fault_df_no_htg actual is {actual} and expected is {expected}"
        assert actual == expected, message


class TestFaultOnInt(object):

    def fault_df_on_output_int(self) -> pd.DataFrame:
        data = {
            TEST_MIX_TEMP_COL: [80.0, 81.0, 79.0, 80.5, 82.0, 80.0],
            TEST_SUPPLY_TEMP_COL: [40.0, 41.0, 42.0, 43.0, 40.5, 40.0],
            TEST_HEATING_COIL_SIG_COL: [0.55, 0.56, 0.54, 0.55, 0.57, 0.55],
            TEST_SUPPLY_VFD_SPEED_COL: [55, 56, 54, 55, 57, 55],
        }
        return pd.DataFrame(data)

    def test_fault_on_int(self):
        with pytest.raises(
            TypeError,
            match=HelperUtils().float_int_check_err(TEST_SUPPLY_VFD_SPEED_COL),
        ):
            fc5.apply(self.fault_df_on_output_int())


class TestFaultOnFloatGreaterThanOne(object):

    def fault_df_on_output_greater_than_one(self) -> pd.DataFrame:
        data = {
            TEST_MIX_TEMP_COL: [80.0, 81.0, 79.0, 80.5, 82.0, 80.0],
            TEST_SUPPLY_TEMP_COL: [40.0, 41.0, 42.0, 43.0, 40.5, 40.0],
            TEST_HEATING_COIL_SIG_COL: [0.55, 0.56, 0.54, 0.55, 0.57, 0.55],
            TEST_SUPPLY_VFD_SPEED_COL: [1.1, 1.2, 1.1, 1.3, 1.1, 1.2],
        }
        return pd.DataFrame(data)

    def test_fault_on_float_greater_than_one(self):
        with pytest.raises(
            TypeError,
            match=HelperUtils().float_max_check_err(TEST_SUPPLY_VFD_SPEED_COL),
        ):
            fc5.apply(self.fault_df_on_output_greater_than_one())


class TestFaultOnMixedTypes(object):

    def fault_df_on_mixed_types(self) -> pd.DataFrame:
        data = {
            TEST_MIX_TEMP_COL: [80.0, 81.0, 79.0, 80.5, 82.0, 80.0],
            TEST_SUPPLY_TEMP_COL: [40.0, 41.0, 42.0, 43.0, 40.5, 40.0],
            TEST_HEATING_COIL_SIG_COL: [0.55, 0.56, 0.54, 0.55, 0.57, 0.55],
            TEST_SUPPLY_VFD_SPEED_COL: [1.1, 0.55, 1.2, 1.3, 0.55, 1.1],
        }
        return pd.DataFrame(data)

    def test_fault_on_mixed_types(self):
        with pytest.raises(
            TypeError,
            match=HelperUtils().float_max_check_err(TEST_SUPPLY_VFD_SPEED_COL),
        ):
            fc5.apply(self.fault_df_on_mixed_types())
