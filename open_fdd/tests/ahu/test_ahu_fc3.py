import pandas as pd
import pytest
from open_fdd.air_handling_unit.faults.fault_condition_three import FaultConditionThree
from open_fdd.air_handling_unit.faults.helper_utils import HelperUtils

'''
To see print statements in pytest run with:
$ py -3.12 -m pytest tests/ahu/test_ahu_fc3.py -rP -s

Mix air temp higher than out temp
'''

# Constants
TEST_MIX_DEGF_ERR_THRES = 2.0
TEST_RETURN_DEGF_ERR_THRES = 2.0
TEST_OUTDOOR_DEGF_ERR_THRES = 5.0
TEST_MIX_TEMP_COL = "mix_air_temp"
TEST_RETURN_TEMP_COL = "return_air_temp"
TEST_OUT_TEMP_COL = "out_air_temp"
TEST_SUPPLY_VFD_SPEED_COL = "supply_vfd_speed"
ROLLING_WINDOW_SIZE = 5

# Initialize FaultConditionThree with a dictionary
fault_condition_params = {
    'MIX_DEGF_ERR_THRES': TEST_MIX_DEGF_ERR_THRES,
    'RETURN_DEGF_ERR_THRES': TEST_RETURN_DEGF_ERR_THRES,
    'OUTDOOR_DEGF_ERR_THRES': TEST_OUTDOOR_DEGF_ERR_THRES,
    'MAT_COL': TEST_MIX_TEMP_COL,
    'RAT_COL': TEST_RETURN_TEMP_COL,
    'OAT_COL': TEST_OUT_TEMP_COL,
    'SUPPLY_VFD_SPEED_COL': TEST_SUPPLY_VFD_SPEED_COL,
    'TROUBLESHOOT_MODE': False,  # default value
    'ROLLING_WINDOW_SIZE': ROLLING_WINDOW_SIZE
}

fc3 = FaultConditionThree(fault_condition_params)

class TestNoFault:

    def no_fault_df(self) -> pd.DataFrame:
        data = {
            TEST_MIX_TEMP_COL: [55.0, 56.0, 57.0, 56.0, 55.5, 55.0],
            TEST_RETURN_TEMP_COL: [70.0, 71.0, 72.0, 70.0, 71.0, 70.0],
            TEST_OUT_TEMP_COL: [50.0, 51.0, 52.0, 50.0, 51.0, 50.0],
            TEST_SUPPLY_VFD_SPEED_COL: [0.8, 0.82, 0.83, 0.8, 0.82, 0.8]
        }
        return pd.DataFrame(data)

    def test_no_fault(self):
        results = fc3.apply(self.no_fault_df())
        actual = results['fc3_flag'].sum()
        expected = 0
        message = f"FC3 no_fault_df actual is {actual} and expected is {expected}"
        assert actual == expected, message

class TestFault:

    def fault_df(self) -> pd.DataFrame:
        data = {
            TEST_MIX_TEMP_COL: [80.0, 81.0, 79.0, 80.5, 82.0, 80.0],
            TEST_RETURN_TEMP_COL: [70.0, 70.5, 71.0, 70.0, 70.5, 70.0],
            TEST_OUT_TEMP_COL: [50.0, 51.0, 52.0, 50.5, 51.0, 50.0],
            TEST_SUPPLY_VFD_SPEED_COL: [0.9, 0.91, 0.92, 0.9, 0.91, 0.9]
        }
        return pd.DataFrame(data)

    def test_fault(self):
        results = fc3.apply(self.fault_df())
        actual = results['fc3_flag'].sum()
        expected = 2
        message = f"FC3 fault_df actual is {actual} and expected is {expected}"
        assert actual == expected, message

class TestFaultOnInt:

    def fault_df_on_output_int(self) -> pd.DataFrame:
        data = {
            TEST_MIX_TEMP_COL: [80.0, 81.0, 79.0, 80.5, 82.0, 80.0],
            TEST_RETURN_TEMP_COL: [70.0, 70.5, 71.0, 70.0, 70.5, 70.0],
            TEST_OUT_TEMP_COL: [50.0, 51.0, 52.0, 50.5, 51.0, 50.0],
            TEST_SUPPLY_VFD_SPEED_COL: [99, 99, 99, 99, 99, 99],
        }
        return pd.DataFrame(data)

    def test_fault_on_int(self):
        with pytest.raises(TypeError, 
                           match=HelperUtils().float_int_check_err(TEST_SUPPLY_VFD_SPEED_COL)):
            fc3.apply(self.fault_df_on_output_int())

class TestFaultOnFloatGreaterThanOne:

    def fault_df_on_output_greater_than_one(self) -> pd.DataFrame:
        data = {
            TEST_MIX_TEMP_COL: [80.0, 81.0, 79.0, 80.5, 82.0, 80.0],
            TEST_RETURN_TEMP_COL: [70.0, 70.5, 71.0, 70.0, 70.5, 70.0],
            TEST_OUT_TEMP_COL: [50.0, 51.0, 52.0, 50.5, 51.0, 50.0],
            TEST_SUPPLY_VFD_SPEED_COL: [1.1, 1.2, 1.3, 1.1, 1.2, 1.1],
        }
        return pd.DataFrame(data)

    def test_fault_on_float_greater_than_one(self):
        with pytest.raises(TypeError,
                           match=HelperUtils().float_max_check_err(TEST_SUPPLY_VFD_SPEED_COL)):
            fc3.apply(self.fault_df_on_output_greater_than_one())

class TestFaultOnMixedTypes:

    def fault_df_on_mixed_types(self) -> pd.DataFrame:
        data = {
            TEST_MIX_TEMP_COL: [80.0, 81.0, 79.0, 80.5, 82.0, 80.0],
            TEST_RETURN_TEMP_COL: [70.0, 70.5, 71.0, 70.0, 70.5, 70.0],
            TEST_OUT_TEMP_COL: [50.0, 51.0, 52.0, 50.5, 51.0, 50.0],
            TEST_SUPPLY_VFD_SPEED_COL: [1.1, 0.91, 1.3, 1.1, 0.92, 1.1],
        }
        return pd.DataFrame(data)

    def test_fault_on_mixed_types(self):
        with pytest.raises(TypeError,
                           match=HelperUtils().float_max_check_err(TEST_SUPPLY_VFD_SPEED_COL)):
            fc3.apply(self.fault_df_on_mixed_types())
