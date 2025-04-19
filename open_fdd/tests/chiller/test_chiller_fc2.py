import pandas as pd
import pytest

from open_fdd.chiller_plant.faults import FaultConditionTwo
from open_fdd.core.exceptions import MissingColumnError

# Constants for test cases
TEST_FLOW_ERR_THRESHOLD = 10.0  # Error threshold for flow in GPM
TEST_PUMP_SPEED_MAX = 0.9  # Maximum pump speed percentage
TEST_PUMP_SPEED_ERR_THRESHOLD = 0.05  # Error threshold for pump speed percentage
TEST_FLOW_COL = "flow_gpm"
TEST_PUMP_SPEED_COL = "pump_speed"

ROLLING_WINDOW_SIZE = 5

# Initialize FaultConditionTwo with a dictionary
fault_condition_params = {
    "FLOW_ERROR_THRESHOLD": TEST_FLOW_ERR_THRESHOLD,
    "PUMP_SPEED_PERCENT_MAX": TEST_PUMP_SPEED_MAX,
    "PUMP_SPEED_PERCENT_ERR_THRES": TEST_PUMP_SPEED_ERR_THRESHOLD,
    "FLOW_COL": TEST_FLOW_COL,
    "PUMP_SPEED_COL": TEST_PUMP_SPEED_COL,
    "ROLLING_WINDOW_SIZE": ROLLING_WINDOW_SIZE,
}

fc_flow = FaultConditionTwo(fault_condition_params)


class TestMissingColumn:
    def missing_col_df(self) -> pd.DataFrame:
        data = {
            TEST_FLOW_COL: [5.0, 8.0, 9.0, 15.0, 7.0],
            # Missing pump speed column
        }
        return pd.DataFrame(data)

    def test_missing_column(self):
        with pytest.raises(MissingColumnError):
            fc_flow.apply(self.missing_col_df())


class TestNoFault:
    def no_fault_df(self) -> pd.DataFrame:
        data = {
            TEST_FLOW_COL: [11.0, 11.0, 12.0, 12.0, 12.5],  # Flow above threshold
            TEST_PUMP_SPEED_COL: [0.5, 0.45, 0.55, 0.45, 0.55],  # Above threshold
        }
        return pd.DataFrame(data)

    def test_no_fault(self):
        results = fc_flow.apply(self.no_fault_df())
        actual = results["fc2_flag"].sum()
        expected = 0
        message = f"FC2 no_fault_df actual is {actual} and expected is {expected}"
        assert actual == expected, message


class TestFault:
    def fault_df(self) -> pd.DataFrame:
        data = {
            TEST_FLOW_COL: [
                6.0,
                6.1,
                6.2,
                6.3,
                6.4,
                12.0,
                6.0,
                6.1,
                6.2,
                6.3,
                6.4,
            ],  # 6th row interrupts the fault condition
            TEST_PUMP_SPEED_COL: [
                0.97,
                0.98,
                0.98,
                0.97,
                0.99,
                0.95,
                0.97,
                0.98,
                0.98,
                0.97,
                0.99,
            ],  # All above threshold
        }
        return pd.DataFrame(data)

    def test_fault(self):
        results = fc_flow.apply(self.fault_df())
        actual = results["fc2_flag"].sum()  # Fault flags counted
        expected = 2  # 5 faults, interruption, then 5 more faults = 2 total flags
        message = f"FC2 fault_df actual is {actual} and expected is {expected}"
        assert actual == expected, message
