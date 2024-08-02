import pandas as pd
import pytest
from open_fdd.air_handling_unit.faults.fault_condition_ten import FaultConditionTen
from open_fdd.air_handling_unit.faults.helper_utils import HelperUtils

'''
To see print statements in pytest run with:
$ py -3.12 -m pytest tests/ahu/test_ahu_fc10.py -rP -s

SAT and MAT should be approx equal in OS3
'''

# Constants
TEST_OAT_DEGF_ERR_THRES = 5.0
TEST_MIX_DEGF_ERR_THRES = 2.0
TEST_OAT_COL = "out_air_temp"
TEST_MAT_COL = "mix_air_temp"
TEST_COOLING_COIL_SIG_COL = "cooling_sig_col"
TEST_MIX_AIR_DAMPER_COL = "economizer_sig_col"
ROLLING_WINDOW_SIZE = 5

# Initialize FaultConditionTen with a dictionary
fault_condition_params = {
    'OUTDOOR_DEGF_ERR_THRES': TEST_OAT_DEGF_ERR_THRES,
    'MIX_DEGF_ERR_THRES': TEST_MIX_DEGF_ERR_THRES,
    'OAT_COL': TEST_OAT_COL,
    'MAT_COL': TEST_MAT_COL,
    'COOLING_SIG_COL': TEST_COOLING_COIL_SIG_COL,
    'ECONOMIZER_SIG_COL': TEST_MIX_AIR_DAMPER_COL,
    'TROUBLESHOOT_MODE': False,
    'ROLLING_WINDOW_SIZE': ROLLING_WINDOW_SIZE
}

fc10 = FaultConditionTen(fault_condition_params)

class TestFaultConditionTen:

    def no_fault_df_no_econ(self) -> pd.DataFrame:
        data = {
            TEST_MAT_COL: [55, 55, 55, 55, 55, 55],
            TEST_OAT_COL: [56, 56, 56, 56, 56, 56],
            TEST_COOLING_COIL_SIG_COL: [0.11, 0.11, 0.11, 0.11, 0.11, 0.11],
            TEST_MIX_AIR_DAMPER_COL: [0.99, 0.99, 0.99, 0.99, 0.99, 0.99],
        }
        return pd.DataFrame(data)

    def fault_df_in_econ(self) -> pd.DataFrame:
        data = {
            TEST_MAT_COL: [55, 55, 55, 55, 55, 55],
            TEST_OAT_COL: [75, 75, 75, 75, 75, 75],
            TEST_COOLING_COIL_SIG_COL: [0.11, 0.11, 0.11, 0.11, 0.11, 0.11],
            TEST_MIX_AIR_DAMPER_COL: [0.99, 0.99, 0.99, 0.99, 0.99, 0.99],
        }
        return pd.DataFrame(data)

    def test_no_fault_no_econ(self):
        results = fc10.apply(self.no_fault_df_no_econ())
        actual = results['fc10_flag'].sum()
        expected = 0
        message = f"FC10 no_fault_df_no_econ actual is {actual} and expected is {expected}"
        assert actual == expected, message

    def test_fault_in_econ(self):
        results = fc10.apply(self.fault_df_in_econ())
        actual = results['fc10_flag'].sum()
        expected = 2
        message = f"FC10 fault_df_in_econ actual is {actual} and expected is {expected}"
        assert actual == expected, message

class TestFaultOnInt:

    def fault_df_on_output_int(self) -> pd.DataFrame:
        data = {
            TEST_MAT_COL: [55, 55, 55, 55, 55, 55],
            TEST_OAT_COL: [75, 75, 75, 75, 75, 75],
            TEST_COOLING_COIL_SIG_COL: [11, 11, 11, 11, 11, 11],  # Incorrect type
            TEST_MIX_AIR_DAMPER_COL: [0.80, 0.80, 0.80, 0.80, 0.80, 0.80],
        }
        return pd.DataFrame(data)

    def test_fault_on_int(self):
        with pytest.raises(TypeError,
                           match=HelperUtils().float_int_check_err(TEST_COOLING_COIL_SIG_COL)):
            fc10.apply(self.fault_df_on_output_int())

class TestFaultOnFloatGreaterThanOne:

    def fault_df_on_output_greater_than_one(self) -> pd.DataFrame:
        data = {
            TEST_MAT_COL: [55, 55, 55, 55, 55, 55],
            TEST_OAT_COL: [75, 75, 75, 75, 75, 75],
            TEST_COOLING_COIL_SIG_COL: [1.1, 1.2, 1.1, 1.3, 1.1, 1.2],  # Values > 1.0
            TEST_MIX_AIR_DAMPER_COL: [0.80, 0.80, 0.80, 0.80, 0.80, 0.80],
        }
        return pd.DataFrame(data)

    def test_fault_on_float_greater_than_one(self):
        with pytest.raises(TypeError,
                           match=HelperUtils().float_max_check_err(TEST_COOLING_COIL_SIG_COL)):
            fc10.apply(self.fault_df_on_output_greater_than_one())

class TestFaultOnMixedTypes:

    def fault_df_on_mixed_types(self) -> pd.DataFrame:
        data = {
            TEST_MAT_COL: [55, 55, 55, 55, 55, 55],
            TEST_OAT_COL: [75, 75, 75, 75, 75, 75],
            TEST_COOLING_COIL_SIG_COL: [1.1, 0.55, 1.2, 1.3, 0.55, 1.1],  # Mixed types
            TEST_MIX_AIR_DAMPER_COL: [0.80, 0.80, 0.80, 0.80, 0.80, 0.80],
        }
        return pd.DataFrame(data)

    def test_fault_on_mixed_types(self):
        with pytest.raises(TypeError,
                           match=HelperUtils().float_max_check_err(TEST_COOLING_COIL_SIG_COL)):
            fc10.apply(self.fault_df_on_mixed_types())

if __name__ == "__main__":
    pytest.main()
