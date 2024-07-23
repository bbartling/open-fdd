from faults import FaultConditionOne, HelperUtils
import pandas as pd
import pytest

'''
to see print statements in pytest run with
$ pytest tests/unit/test_ahu_fc1.py -rP

duct static pressure low when fan at full speed
'''

TEST_VFD_ERR_THRESHOLD = 0.05
TEST_VFD_SPEED_MAX = 0.7
TEST_DUCT_STATIC_ERR_THRESHOLD = 0.1
TEST_DUCT_STATIC_COL = "duct_static"
TEST_DUCT_STATIC_SETPOINT_COL = "duct_static_setpoint"
TEST_SUPPLY_VFD_SPEED_COL = "supply_vfd_speed"


fc1 = FaultConditionOne(
    TEST_VFD_ERR_THRESHOLD,
    TEST_VFD_SPEED_MAX,
    TEST_DUCT_STATIC_ERR_THRESHOLD,
    TEST_DUCT_STATIC_COL,
    TEST_SUPPLY_VFD_SPEED_COL,
    TEST_DUCT_STATIC_SETPOINT_COL,
)


class TestNoFault(object):

    def no_fault_df(self) -> pd.DataFrame:
        data = {
            TEST_DUCT_STATIC_COL: [1.1],
            TEST_DUCT_STATIC_SETPOINT_COL: [1.0],
            TEST_SUPPLY_VFD_SPEED_COL: [0.80],
        }
        return pd.DataFrame(data)

    def test_no_fault(self):
        results = fc1.apply(self.no_fault_df())
        actual = results.loc[0, 'fc1_flag']
        expected = 0.0
        message = f"FC1 no_fault_df actual is {actual} and expected is {expected}"
        assert actual == expected, message


class TestFault(object):

    def fault_df(self) -> pd.DataFrame:
        data = {
            TEST_DUCT_STATIC_COL: [.8],
            TEST_DUCT_STATIC_SETPOINT_COL: [1.0],
            TEST_SUPPLY_VFD_SPEED_COL: [0.99],
        }
        return pd.DataFrame(data)

    def test_fault(self):
        results = fc1.apply(self.fault_df())
        actual = results.loc[0, 'fc1_flag']
        expected = 1.0
        message = f"FC1 fault_df actual is {actual} and expected is {expected}"
        assert actual == expected, message


class TestFaultOnInt(object):

    def fault_df_on_output_int(self) -> pd.DataFrame:
        data = {
            TEST_DUCT_STATIC_COL: [.8],
            TEST_DUCT_STATIC_SETPOINT_COL: [1.0],
            TEST_SUPPLY_VFD_SPEED_COL: [99],
        }
        return pd.DataFrame(data)

    def test_fault_on_int(self):
        with pytest.raises(TypeError, 
                           match=HelperUtils().float_int_check_err(TEST_SUPPLY_VFD_SPEED_COL)):
            fc1.apply(self.fault_df_on_output_int())


class TestFaultOnFloatGreaterThanOne(object):

    def fault_df_on_output_greater_than_one(self) -> pd.DataFrame:
        data = {
            TEST_DUCT_STATIC_COL: [.8],
            TEST_DUCT_STATIC_SETPOINT_COL: [1.0],
            TEST_SUPPLY_VFD_SPEED_COL: [99.0],
        }
        return pd.DataFrame(data)

    def test_fault_on_float_greater_than_one(self):
        with pytest.raises(TypeError,
                           match=HelperUtils().float_max_check_err(TEST_SUPPLY_VFD_SPEED_COL)):
            fc1.apply(self.fault_df_on_output_greater_than_one())
