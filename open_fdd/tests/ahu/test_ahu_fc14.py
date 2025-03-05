import pandas as pd
import pytest
from open_fdd.air_handling_unit.faults import (
    FaultConditionFourteen,
)
from open_fdd.core.exceptions import MissingColumnError
from open_fdd.air_handling_unit.faults.helper_utils import HelperUtils

"""
To see print statements in pytest run with:
$ py -3.12 -m pytest open_fdd/tests/ahu/test_ahu_fc14.py -rP -s

Temp drop across inactive clg coil in OS1 & OS2
"""

# Constants
TEST_DELTA_SUPPLY_FAN = 2.0
TEST_COIL_TEMP_ENTER_ERR_THRES = 1.0
TEST_COIL_TEMP_LEAVE_ERR_THRES = 1.0
TEST_MIX_DEGF_ERR_THRES = 2.0
TEST_OUTDOOR_DEGF_ERR_THRES = 5.0
TEST_AHU_MIN_OA_DPR = 0.2
TEST_CLG_COIL_ENTER_TEMP_COL = "clg_enter_air_temp"
TEST_CLG_COIL_LEAVE_TEMP_COL = "clg_leave_air_temp"
TEST_CLG_COIL_CMD_COL = "cooling_sig_col"
TEST_HTG_COIL_CMD_COL = "heating_sig_col"
TEST_MIX_AIR_DAMPER_COL = "economizer_sig_col"
TEST_SUPPLY_VFD_SPEED_COL = "supply_vfd_speed"
TEST_OAT_COL = "out_air_temp"
TEST_MAT_COL = "mix_air_temp"
ROLLING_WINDOW_SIZE = 5

# Initialize FaultConditionFourteen with a dictionary
fault_condition_params = {
    "DELTA_T_SUPPLY_FAN": TEST_DELTA_SUPPLY_FAN,
    "COIL_TEMP_ENTER_ERR_THRES": TEST_COIL_TEMP_ENTER_ERR_THRES,
    "COIL_TEMP_LEAV_ERR_THRES": TEST_COIL_TEMP_LEAVE_ERR_THRES,
    "MIX_DEGF_ERR_THRES": TEST_MIX_DEGF_ERR_THRES,
    "OUTDOOR_DEGF_ERR_THRES": TEST_OUTDOOR_DEGF_ERR_THRES,
    "AHU_MIN_OA_DPR": TEST_AHU_MIN_OA_DPR,
    "CLG_COIL_ENTER_TEMP_COL": TEST_CLG_COIL_ENTER_TEMP_COL,
    "CLG_COIL_LEAVE_TEMP_COL": TEST_CLG_COIL_LEAVE_TEMP_COL,
    "COOLING_SIG_COL": TEST_CLG_COIL_CMD_COL,
    "HEATING_SIG_COL": TEST_HTG_COIL_CMD_COL,
    "ECONOMIZER_SIG_COL": TEST_MIX_AIR_DAMPER_COL,
    "SUPPLY_VFD_SPEED_COL": TEST_SUPPLY_VFD_SPEED_COL,
    "OAT_COL": TEST_OAT_COL,
    "MAT_COL": TEST_MAT_COL,
    "TROUBLESHOOT_MODE": False,
    "ROLLING_WINDOW_SIZE": ROLLING_WINDOW_SIZE,
}

fc14 = FaultConditionFourteen(fault_condition_params)


class TestFaultConditionFourteen:

    def no_fault_df_econ(self) -> pd.DataFrame:
        data = {
            TEST_CLG_COIL_ENTER_TEMP_COL: [55, 55, 55, 55, 55, 55],
            TEST_CLG_COIL_LEAVE_TEMP_COL: [56.5, 56.5, 56.5, 56.5, 56.5, 56.5],
            TEST_CLG_COIL_CMD_COL: [0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
            TEST_HTG_COIL_CMD_COL: [0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
            TEST_MIX_AIR_DAMPER_COL: [0.55, 0.55, 0.55, 0.55, 0.55, 0.55],
            TEST_SUPPLY_VFD_SPEED_COL: [0.55, 0.55, 0.55, 0.55, 0.55, 0.55],
        }
        return pd.DataFrame(data)

    def no_fault_df_htg(self) -> pd.DataFrame:
        data = {
            TEST_CLG_COIL_ENTER_TEMP_COL: [55, 55, 55, 55, 55, 55],
            TEST_CLG_COIL_LEAVE_TEMP_COL: [56.5, 56.5, 56.5, 56.5, 56.5, 56.5],
            TEST_CLG_COIL_CMD_COL: [0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
            TEST_HTG_COIL_CMD_COL: [0.55, 0.55, 0.55, 0.55, 0.55, 0.55],
            TEST_MIX_AIR_DAMPER_COL: [
                TEST_AHU_MIN_OA_DPR,
                TEST_AHU_MIN_OA_DPR,
                TEST_AHU_MIN_OA_DPR,
                TEST_AHU_MIN_OA_DPR,
                TEST_AHU_MIN_OA_DPR,
                TEST_AHU_MIN_OA_DPR,
            ],
            TEST_SUPPLY_VFD_SPEED_COL: [0.55, 0.55, 0.55, 0.55, 0.55, 0.55],
        }
        return pd.DataFrame(data)

    def fault_df_in_econ(self) -> pd.DataFrame:
        data = {
            TEST_CLG_COIL_ENTER_TEMP_COL: [55, 55, 55, 55, 55, 55],
            TEST_CLG_COIL_LEAVE_TEMP_COL: [50.5, 50.5, 50.5, 50.5, 50.5, 50.5],
            TEST_CLG_COIL_CMD_COL: [0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
            TEST_HTG_COIL_CMD_COL: [0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
            TEST_MIX_AIR_DAMPER_COL: [0.55, 0.55, 0.55, 0.55, 0.55, 0.55],
            TEST_SUPPLY_VFD_SPEED_COL: [0.55, 0.55, 0.55, 0.55, 0.55, 0.55],
        }
        return pd.DataFrame(data)

    def fault_df_in_htg(self) -> pd.DataFrame:
        data = {
            TEST_CLG_COIL_ENTER_TEMP_COL: [55, 55, 55, 55, 55, 55],
            TEST_CLG_COIL_LEAVE_TEMP_COL: [50.5, 50.5, 50.5, 50.5, 50.5, 50.5],
            TEST_CLG_COIL_CMD_COL: [0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
            TEST_HTG_COIL_CMD_COL: [0.55, 0.55, 0.55, 0.55, 0.55, 0.55],
            TEST_MIX_AIR_DAMPER_COL: [
                TEST_AHU_MIN_OA_DPR,
                TEST_AHU_MIN_OA_DPR,
                TEST_AHU_MIN_OA_DPR,
                TEST_AHU_MIN_OA_DPR,
                TEST_AHU_MIN_OA_DPR,
                TEST_AHU_MIN_OA_DPR,
            ],
            TEST_SUPPLY_VFD_SPEED_COL: [0.55, 0.55, 0.55, 0.55, 0.55, 0.55],
        }
        return pd.DataFrame(data)

    def test_no_fault_econ(self):
        results = fc14.apply(self.no_fault_df_econ())
        actual = results["fc14_flag"].sum()
        expected = 0
        message = f"FC14 no_fault_df_econ actual is {actual} and expected is {expected}"
        assert actual == expected, message

    def test_no_fault_htg(self):
        results = fc14.apply(self.no_fault_df_htg())
        actual = results["fc14_flag"].sum()
        expected = 0
        message = f"FC14 no_fault_df_htg actual is {actual} and expected is {expected}"
        assert actual == expected, message

    def test_fault_in_econ(self):
        results = fc14.apply(self.fault_df_in_econ())
        actual = results["fc14_flag"].sum()
        expected = 2
        message = f"FC14 fault_df_in_econ actual is {actual} and expected is {expected}"
        assert actual == expected, message

    def test_fault_in_htg(self):
        results = fc14.apply(self.fault_df_in_htg())
        actual = results["fc14_flag"].sum()
        expected = 2
        message = f"FC14 fault_df_in_htg actual is {actual} and expected is {expected}"
        assert actual == expected, message


class TestFaultOnInt:

    def fault_df_on_output_int(self) -> pd.DataFrame:
        data = {
            TEST_CLG_COIL_ENTER_TEMP_COL: [55, 55, 55, 55, 55, 55],
            TEST_CLG_COIL_LEAVE_TEMP_COL: [50.5, 50.5, 50.5, 50.5, 50.5, 50.5],
            TEST_CLG_COIL_CMD_COL: [0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
            TEST_HTG_COIL_CMD_COL: [0.55, 0.55, 0.55, 0.55, 0.55, 0.55],
            TEST_MIX_AIR_DAMPER_COL: [55, 55, 55, 55, 55, 55],  # Incorrect type
            TEST_SUPPLY_VFD_SPEED_COL: [0.55, 0.55, 0.55, 0.55, 0.55, 0.55],
        }
        return pd.DataFrame(data)

    def test_fault_on_int(self):
        with pytest.raises(
            TypeError, match=HelperUtils().float_int_check_err(TEST_MIX_AIR_DAMPER_COL)
        ):
            fc14.apply(self.fault_df_on_output_int())


class TestFaultOnFloatGreaterThanOne:

    def fault_df_on_output_greater_than_one(self) -> pd.DataFrame:
        data = {
            TEST_CLG_COIL_ENTER_TEMP_COL: [55, 55, 55, 55, 55, 55],
            TEST_CLG_COIL_LEAVE_TEMP_COL: [50.5, 50.5, 50.5, 50.5, 50.5, 50.5],
            TEST_CLG_COIL_CMD_COL: [0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
            TEST_HTG_COIL_CMD_COL: [0.55, 0.55, 0.55, 0.55, 0.55, 0.55],
            TEST_MIX_AIR_DAMPER_COL: [1.1, 1.2, 1.1, 1.3, 1.1, 1.2],  # Values > 1.0
            TEST_SUPPLY_VFD_SPEED_COL: [0.55, 0.55, 0.55, 0.55, 0.55, 0.55],
        }
        return pd.DataFrame(data)

    def test_fault_on_float_greater_than_one(self):
        with pytest.raises(
            TypeError, match=HelperUtils().float_max_check_err(TEST_MIX_AIR_DAMPER_COL)
        ):
            fc14.apply(self.fault_df_on_output_greater_than_one())


class TestFaultOnMixedTypes:

    def fault_df_on_mixed_types(self) -> pd.DataFrame:
        data = {
            TEST_CLG_COIL_ENTER_TEMP_COL: [55, 55, 55, 55, 55, 55],
            TEST_CLG_COIL_LEAVE_TEMP_COL: [50.5, 50.5, 50.5, 50.5, 50.5, 50.5],
            TEST_CLG_COIL_CMD_COL: [0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
            TEST_HTG_COIL_CMD_COL: [0.55, 0.55, 0.55, 0.55, 0.55, 0.55],
            TEST_MIX_AIR_DAMPER_COL: [1.1, 0.55, 1.2, 1.3, 0.55, 1.1],  # Mixed types
            TEST_SUPPLY_VFD_SPEED_COL: [0.55, 0.55, 0.55, 0.55, 0.55, 0.55],
        }
        return pd.DataFrame(data)

    def test_fault_on_mixed_types(self):
        with pytest.raises(
            TypeError, match=HelperUtils().float_max_check_err(TEST_MIX_AIR_DAMPER_COL)
        ):
            fc14.apply(self.fault_df_on_mixed_types())


if __name__ == "__main__":
    pytest.main()
