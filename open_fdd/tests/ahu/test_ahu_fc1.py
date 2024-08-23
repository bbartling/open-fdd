import pandas as pd
import pytest
from open_fdd.air_handling_unit.faults.fault_condition_one import FaultConditionOne
from open_fdd.air_handling_unit.faults.helper_utils import HelperUtils
from open_fdd.air_handling_unit.faults.fault_condition import MissingColumnError


# Constants
TEST_VFD_ERR_THRESHOLD = 0.05
TEST_VFD_SPEED_MAX = 0.7
TEST_DUCT_STATIC_ERR_THRESHOLD = 0.1
TEST_DUCT_STATIC_COL = "duct_static"
TEST_DUCT_STATIC_SETPOINT_COL = "duct_static_setpoint"
TEST_SUPPLY_VFD_SPEED_COL = "supply_vfd_speed"
ROLLING_WINDOW_SIZE = 5

# Initialize FaultConditionOne with a dictionary
fault_condition_params = {
    "VFD_SPEED_PERCENT_ERR_THRES": TEST_VFD_ERR_THRESHOLD,
    "VFD_SPEED_PERCENT_MAX": TEST_VFD_SPEED_MAX,
    "DUCT_STATIC_INCHES_ERR_THRES": TEST_DUCT_STATIC_ERR_THRESHOLD,
    "DUCT_STATIC_COL": TEST_DUCT_STATIC_COL,
    "SUPPLY_VFD_SPEED_COL": TEST_SUPPLY_VFD_SPEED_COL,
    "DUCT_STATIC_SETPOINT_COL": TEST_DUCT_STATIC_SETPOINT_COL,
    "TROUBLESHOOT_MODE": False,  # default value
    "ROLLING_WINDOW_SIZE": ROLLING_WINDOW_SIZE,  # rolling sum window size
}

fc1 = FaultConditionOne(fault_condition_params)


class TestMissingColumn:

    def missing_col_df(self) -> pd.DataFrame:
        data = {
            TEST_DUCT_STATIC_COL: [0.99, 0.99, 0.99, 0.99, 0.99, 0.99],
            # Missing TEST_SUPPLY_VFD_SPEED_COL
            TEST_DUCT_STATIC_SETPOINT_COL: [1.0, 1.0, 1.0, 1.0, 1.0, 1.0],
        }
        return pd.DataFrame(data)

    def test_missing_column(self):
        with pytest.raises(MissingColumnError):
            fc1.apply(self.missing_col_df())


class TestNoFault:

    def no_fault_df(self) -> pd.DataFrame:
        data = {
            TEST_DUCT_STATIC_COL: [0.99, 0.99, 0.99, 0.99, 0.99, 0.99],
            TEST_DUCT_STATIC_SETPOINT_COL: [1.0, 1.0, 1.0, 1.0, 1.0, 1.0],
            TEST_SUPPLY_VFD_SPEED_COL: [0.8, 0.8, 0.8, 0.8, 0.8, 0.8],
        }
        return pd.DataFrame(data)

    def test_no_fault(self):
        results = fc1.apply(self.no_fault_df())
        actual = results["fc1_flag"].sum()
        expected = 0
        message = f"FC1 no_fault_df actual is {actual} and expected is {expected}"
        assert actual == expected, message


class TestFault:

    def fault_df(self) -> pd.DataFrame:
        data = {
            TEST_DUCT_STATIC_COL: [
                0.7,
                0.7,
                0.6,
                0.7,
                0.65,
                0.55,
                0.99,
                0.99,
                0.6,
                0.7,
                0.65,
                0.55,
                0.6,
                0.7,
                0.65,
                0.55,
                0.6,
            ],
            TEST_DUCT_STATIC_SETPOINT_COL: [
                1.0,
                1.0,
                1.0,
                1.0,
                1.0,
                1.0,
                1.0,
                1.0,
                1.0,
                1.0,
                1.0,
                1.0,
                1.0,
                1.0,
                1.0,
                1.0,
                1.0,
            ],
            TEST_SUPPLY_VFD_SPEED_COL: [
                0.99,
                0.95,
                0.96,
                0.97,
                0.98,
                0.98,
                0.5,
                0.55,
                0.96,
                0.97,
                0.98,
                0.98,
                0.96,
                0.97,
                0.98,
                0.98,
                0.96,
            ],
        }
        return pd.DataFrame(data)

    def test_fault(self):
        results = fc1.apply(self.fault_df())
        actual = results["fc1_flag"].sum()

        # accumilated 5 faults need to happen before an "official fault"
        # in TEST_DUCT_STATIC_COL after the 5 first values there is 3 faults
        # then artificially adjust fake fan data back to normal and another 5
        # needs happen per ROLLING_WINDOW_SIZE and then 4 faults after that.
        # so expected = 3 + 4.
        expected = 3 + 4
        message = f"FC1 fault_df actual is {actual} and expected is {expected}"
        assert actual == expected, message


class TestFaultOnInt:

    def fault_df_on_output_int(self) -> pd.DataFrame:
        data = {
            TEST_DUCT_STATIC_COL: [0.8] * 6,
            TEST_DUCT_STATIC_SETPOINT_COL: [1.0] * 6,
            TEST_SUPPLY_VFD_SPEED_COL: [99] * 6,
        }
        return pd.DataFrame(data)

    def test_fault_on_int(self):
        with pytest.raises(
            TypeError,
            match=HelperUtils().float_int_check_err(TEST_SUPPLY_VFD_SPEED_COL),
        ):
            fc1.apply(self.fault_df_on_output_int())


class TestFaultOnFloatGreaterThanOne:

    def fault_df_on_output_greater_than_one(self) -> pd.DataFrame:
        data = {
            TEST_DUCT_STATIC_COL: [0.8] * 6,
            TEST_DUCT_STATIC_SETPOINT_COL: [1.0] * 6,
            TEST_SUPPLY_VFD_SPEED_COL: [99.0] * 6,
        }
        return pd.DataFrame(data)

    def test_fault_on_float_greater_than_one(self):
        with pytest.raises(
            TypeError,
            match=HelperUtils().float_max_check_err(TEST_SUPPLY_VFD_SPEED_COL),
        ):
            fc1.apply(self.fault_df_on_output_greater_than_one())
