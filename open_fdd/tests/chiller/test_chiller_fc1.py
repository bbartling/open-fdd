import pandas as pd
import pytest

from open_fdd.chiller_plant.faults import FaultConditionOne
from open_fdd.core.exceptions import MissingColumnError

# Constants for test cases
TEST_PUMP_ERR_THRESHOLD = 0.05
TEST_PUMP_SPEED_MAX = 0.9
TEST_DIFF_PRESSURE_ERR_THRESHOLD = 0.1
TEST_DIFF_PRESSURE_COL = "diff_pressure"
TEST_DIFF_PRESSURE_SETPOINT_COL = "diff_pressure_setpoint"
TEST_PUMP_SPEED_COL = "pump_speed"

ROLLING_WINDOW_SIZE = 5

# Initialize FaultConditionPump with a dictionary
fault_condition_params = {
    "PUMP_SPEED_PERCENT_ERR_THRES": TEST_PUMP_ERR_THRESHOLD,
    "PUMP_SPEED_PERCENT_MAX": TEST_PUMP_SPEED_MAX,
    "DIFF_PRESSURE_PSI_ERR_THRES": TEST_DIFF_PRESSURE_ERR_THRESHOLD,
    "DIFF_PRESSURE_COL": TEST_DIFF_PRESSURE_COL,
    "PUMP_SPEED_COL": TEST_PUMP_SPEED_COL,
    "DIFF_PRESSURE_SETPOINT_COL": TEST_DIFF_PRESSURE_SETPOINT_COL,
    "TROUBLESHOOT_MODE": False,
    "ROLLING_WINDOW_SIZE": ROLLING_WINDOW_SIZE,
}

fc_pump = FaultConditionOne(fault_condition_params)


class TestMissingColumn:
    def missing_col_df(self) -> pd.DataFrame:
        data = {
            TEST_DIFF_PRESSURE_COL: [8.0, 8.1, 8.2, 8.1, 8.0, 8.0],
            # Missing TEST_PUMP_SPEED_COL
            TEST_DIFF_PRESSURE_SETPOINT_COL: [10.0, 10.0, 10.0, 10.0, 10.0, 10.0],
        }
        return pd.DataFrame(data)

    def test_missing_column(self):
        with pytest.raises(MissingColumnError):
            fc_pump.apply(self.missing_col_df())


class TestNoFault:
    def no_fault_df(self) -> pd.DataFrame:
        data = {
            TEST_DIFF_PRESSURE_COL: [9.8, 9.9, 9.8, 9.8, 9.9, 9.8],
            TEST_DIFF_PRESSURE_SETPOINT_COL: [10.0, 10.0, 10.0, 10.0, 10.0, 10.0],
            TEST_PUMP_SPEED_COL: [0.7, 0.7, 0.7, 0.7, 0.7, 0.7],
        }
        return pd.DataFrame(data)

    def test_no_fault(self):
        results = fc_pump.apply(self.no_fault_df())
        actual = results["fc_pump_flag"].sum()
        expected = 0
        message = f"FC Pump no_fault_df actual is {actual} and expected is {expected}"
        assert actual == expected, message


class TestFault:
    def fault_df(self) -> pd.DataFrame:
        data = {
            TEST_DIFF_PRESSURE_COL: [
                8.0,
                8.1,
                8.0,
                7.9,
                8.0,
                8.0,
                9.9,
                9.9,
                8.0,
                8.1,
                8.0,
                7.9,
                8.0,
                8.1,
            ],
            TEST_DIFF_PRESSURE_SETPOINT_COL: [
                10.0,
                10.0,
                10.0,
                10.0,
                10.0,
                10.0,
                10.0,
                10.0,
                10.0,
                10.0,
                10.0,
                10.0,
                10.0,
                10.0,
            ],
            TEST_PUMP_SPEED_COL: [
                0.9,
                0.9,
                0.9,
                0.9,
                0.9,
                0.9,
                0.5,
                0.55,
                0.9,
                0.9,
                0.9,
                0.9,
                0.9,
                0.9,
            ],
        }
        return pd.DataFrame(data)

    def test_fault(self):
        results = fc_pump.apply(self.fault_df())
        actual = results["fc_pump_flag"].sum()
        expected = 4  # Adjusted based on the rolling window and fault conditions
        message = f"FC Pump fault_df actual is {actual} and expected is {expected}"
        assert actual == expected, message
