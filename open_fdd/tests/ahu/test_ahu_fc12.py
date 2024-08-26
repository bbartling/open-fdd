import pandas as pd
import pytest
from open_fdd.air_handling_unit.faults import (
    FaultConditionTwelve,
)
from open_fdd.air_handling_unit.faults.helper_utils import HelperUtils

"""
To see print statements in pytest run with:
$ py -3.12 -m pytest tests/ahu/test_ahu_fc12.py -rP -s

SAT too high should be less than MAT. OS3 & OS4
"""

# Constants
TEST_DELTA_SUPPLY_FAN = 2.0
TEST_MIX_DEGF_ERR_THRES = 2.0
TEST_SUPPLY_DEGF_ERR_THRES = 2.0
TEST_AHU_MIN_OA_DPR = 0.2
TEST_SAT_COL = "supply_air_temp"
TEST_MAT_COL = "mix_air_temp"
TEST_COOLING_COIL_SIG_COL = "cooling_sig_col"
TEST_MIX_AIR_DAMPER_COL = "economizer_sig_col"
ROLLING_WINDOW_SIZE = 5

# Initialize FaultConditionTwelve with a dictionary
fault_condition_params = {
    "DELTA_T_SUPPLY_FAN": TEST_DELTA_SUPPLY_FAN,
    "MIX_DEGF_ERR_THRES": TEST_MIX_DEGF_ERR_THRES,
    "SUPPLY_DEGF_ERR_THRES": TEST_SUPPLY_DEGF_ERR_THRES,
    "AHU_MIN_OA_DPR": TEST_AHU_MIN_OA_DPR,
    "SAT_COL": TEST_SAT_COL,
    "MAT_COL": TEST_MAT_COL,
    "COOLING_SIG_COL": TEST_COOLING_COIL_SIG_COL,
    "ECONOMIZER_SIG_COL": TEST_MIX_AIR_DAMPER_COL,
    "TROUBLESHOOT_MODE": False,
    "ROLLING_WINDOW_SIZE": ROLLING_WINDOW_SIZE,
}

fc12 = FaultConditionTwelve(fault_condition_params)


class TestFaultConditionTwelve:

    def no_fault_df_no_econ(self) -> pd.DataFrame:
        data = {
            TEST_SAT_COL: [55, 55, 55, 55, 55, 55],
            TEST_MAT_COL: [56, 56, 56, 56, 56, 56],
            TEST_COOLING_COIL_SIG_COL: [0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
            TEST_MIX_AIR_DAMPER_COL: [
                TEST_AHU_MIN_OA_DPR,
                TEST_AHU_MIN_OA_DPR,
                TEST_AHU_MIN_OA_DPR,
                TEST_AHU_MIN_OA_DPR,
                TEST_AHU_MIN_OA_DPR,
                TEST_AHU_MIN_OA_DPR,
            ],
        }
        return pd.DataFrame(data)

    def fault_df_in_econ_plus_mech(self) -> pd.DataFrame:
        data = {
            TEST_SAT_COL: [66, 66, 66, 66, 66, 66],
            TEST_MAT_COL: [56, 56, 56, 56, 56, 56],
            TEST_COOLING_COIL_SIG_COL: [0.50, 0.50, 0.50, 0.50, 0.50, 0.50],
            TEST_MIX_AIR_DAMPER_COL: [0.99, 0.99, 0.99, 0.99, 0.99, 0.99],
        }
        return pd.DataFrame(data)

    def fault_df_in_mech_clg(self) -> pd.DataFrame:
        data = {
            TEST_SAT_COL: [66, 66, 66, 66, 66, 66],
            TEST_MAT_COL: [56, 56, 56, 56, 56, 56],
            TEST_COOLING_COIL_SIG_COL: [0.99, 0.99, 0.99, 0.99, 0.99, 0.99],
            TEST_MIX_AIR_DAMPER_COL: [
                TEST_AHU_MIN_OA_DPR,
                TEST_AHU_MIN_OA_DPR,
                TEST_AHU_MIN_OA_DPR,
                TEST_AHU_MIN_OA_DPR,
                TEST_AHU_MIN_OA_DPR,
                TEST_AHU_MIN_OA_DPR,
            ],
        }
        return pd.DataFrame(data)

    def test_no_fault_no_econ(self):
        results = fc12.apply(self.no_fault_df_no_econ())
        actual = results["fc12_flag"].sum()
        expected = 0
        message = (
            f"FC12 no_fault_df_no_econ actual is {actual} and expected is {expected}"
        )
        assert actual == expected, message

    def test_fault_in_econ_plus_mech(self):
        results = fc12.apply(self.fault_df_in_econ_plus_mech())
        actual = results["fc12_flag"].sum()
        expected = 2
        message = f"FC12 fault_df_in_econ actual is {actual} and expected is {expected}"
        assert actual == expected, message

    def test_fault_in_mech_clg(self):
        results = fc12.apply(self.fault_df_in_mech_clg())
        actual = results["fc12_flag"].sum()
        expected = 2
        message = (
            f"FC12 fault_df_in_mech_clg actual is {actual} and expected is {expected}"
        )
        assert actual == expected, message


class TestFaultOnInt:

    def fault_df_on_output_int(self) -> pd.DataFrame:
        data = {
            TEST_SAT_COL: [55, 55, 55, 55, 55, 55],
            TEST_MAT_COL: [56, 56, 56, 56, 56, 56],
            TEST_COOLING_COIL_SIG_COL: [0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
            TEST_MIX_AIR_DAMPER_COL: [11, 11, 11, 11, 11, 11],  # Incorrect type
        }
        return pd.DataFrame(data)

    def test_fault_on_int(self):
        with pytest.raises(
            TypeError, match=HelperUtils().float_int_check_err(TEST_MIX_AIR_DAMPER_COL)
        ):
            fc12.apply(self.fault_df_on_output_int())


class TestFaultOnFloatGreaterThanOne:

    def fault_df_on_output_greater_than_one(self) -> pd.DataFrame:
        data = {
            TEST_SAT_COL: [55, 55, 55, 55, 55, 55],
            TEST_MAT_COL: [56, 56, 56, 56, 56, 56],
            TEST_COOLING_COIL_SIG_COL: [0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
            TEST_MIX_AIR_DAMPER_COL: [1.1, 1.2, 1.1, 1.3, 1.1, 1.2],  # Values > 1.0
        }
        return pd.DataFrame(data)

    def test_fault_on_float_greater_than_one(self):
        with pytest.raises(
            TypeError, match=HelperUtils().float_max_check_err(TEST_MIX_AIR_DAMPER_COL)
        ):
            fc12.apply(self.fault_df_on_output_greater_than_one())


class TestFaultOnMixedTypes:

    def fault_df_on_mixed_types(self) -> pd.DataFrame:
        data = {
            TEST_SAT_COL: [55, 55, 55, 55, 55, 55],
            TEST_MAT_COL: [56, 56, 56, 56, 56, 56],
            TEST_COOLING_COIL_SIG_COL: [0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
            TEST_MIX_AIR_DAMPER_COL: [1.1, 0.55, 1.2, 1.3, 0.55, 1.1],  # Mixed types
        }
        return pd.DataFrame(data)

    def test_fault_on_mixed_types(self):
        with pytest.raises(
            TypeError, match=HelperUtils().float_max_check_err(TEST_MIX_AIR_DAMPER_COL)
        ):
            fc12.apply(self.fault_df_on_mixed_types())


if __name__ == "__main__":
    pytest.main()
