import pandas as pd
import pytest
from open_fdd.air_handling_unit.faults.fault_condition_seven import FaultConditionSeven
from open_fdd.air_handling_unit.faults.helper_utils import HelperUtils

'''
To see print statements in pytest run with:
$ py -3.12 -m pytest tests/ahu/test_ahu_fc7.py -rP -s

Supply air temperature too low in full heating.
'''

# Constants
TEST_SUPPLY_DEGF_ERR_THRES = 2.0
TEST_SAT_COL = "supply_air_temp"
TEST_SAT_SETPOINT_COL = "sat_setpoint"
TEST_HEATING_SIG_COL = "heating_sig"
TEST_SUPPLY_VFD_SPEED_COL = "supply_vfd_speed"
ROLLING_WINDOW_SIZE = 5

# Initialize FaultConditionSeven with a dictionary
fault_condition_params = {
    'SUPPLY_DEGF_ERR_THRES': TEST_SUPPLY_DEGF_ERR_THRES,
    'SAT_COL': TEST_SAT_COL,
    'SAT_SETPOINT_COL': TEST_SAT_SETPOINT_COL,
    'HEATING_SIG_COL': TEST_HEATING_SIG_COL,
    'SUPPLY_VFD_SPEED_COL': TEST_SUPPLY_VFD_SPEED_COL,
    'TROUBLESHOOT_MODE': False,  # default value
    'ROLLING_WINDOW_SIZE': ROLLING_WINDOW_SIZE  # rolling sum window size
}

fc7 = FaultConditionSeven(fault_condition_params)

class TestFaultConditionSeven:

    def fault_df(self) -> pd.DataFrame:
        data = {
            TEST_SAT_COL: [65, 64, 63, 62, 61, 60],
            TEST_SAT_SETPOINT_COL: [70, 70, 70, 70, 70, 70],
            TEST_HEATING_SIG_COL: [0.95, 0.96, 0.97, 0.98, 0.99, 1.0],
            TEST_SUPPLY_VFD_SPEED_COL: [0.5, 0.5, 0.5, 0.5, 0.5, 0.5],
        }
        return pd.DataFrame(data)

    def no_fault_df(self) -> pd.DataFrame:
        data = {
            TEST_SAT_COL: [71, 72, 73, 74, 75, 76],
            TEST_SAT_SETPOINT_COL: [70, 70, 70, 70, 70, 70],
            TEST_HEATING_SIG_COL: [0.95, 0.96, 0.97, 0.98, 0.99, 1.0],
            TEST_SUPPLY_VFD_SPEED_COL: [0.5, 0.5, 0.5, 0.5, 0.5, 0.5],
        }
        return pd.DataFrame(data)

    def test_fault_condition_seven(self):
        results = fc7.apply(self.fault_df())
        actual = results['fc7_flag'].sum()
        expected = 2
        message = f"FC7 fault_df actual is {actual} and expected is {expected}"
        assert actual == expected, message

    def test_no_fault_condition_seven(self):
        results = fc7.apply(self.no_fault_df())
        actual = results['fc7_flag'].sum()
        expected = 0
        message = f"FC7 no_fault_df actual is {actual} and expected is {expected}"
        assert actual == expected, message

if __name__ == "__main__":
    pytest.main()
