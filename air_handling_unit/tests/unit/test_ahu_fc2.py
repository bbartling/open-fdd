from faults import FaultConditionTwo, HelperUtils
import pandas as pd
import pytest

'''
to see print statements in pytest run with
$ pytest tests/unit/test_ahu_fc2.py -rP

mix air temp lower than out temp
'''


TEST_OUTDOOR_DEGF_ERR_THRES = 5.
TEST_MIX_DEGF_ERR_THRES = 5.
TEST_RETURN_DEGF_ERR_THRES = 2.
TEST_MIX_TEMP_COL = "mix_air_temp"
TEST_RETURN_TEMP_COL = "return_air_temp"
TEST_OUT_TEMP_COL = "out_air_temp"
TEST_SUPPLY_VFD_SPEED_COL = "supply_vfd_speed"


fc2 = FaultConditionTwo(
    TEST_MIX_DEGF_ERR_THRES,
    TEST_RETURN_DEGF_ERR_THRES,
    TEST_OUTDOOR_DEGF_ERR_THRES,
    TEST_MIX_TEMP_COL,
    TEST_RETURN_TEMP_COL,
    TEST_OUT_TEMP_COL,
    TEST_SUPPLY_VFD_SPEED_COL,
)



class TestNoFault(object):

    def no_fault_df(self) -> pd.DataFrame:
        data = {
            TEST_MIX_TEMP_COL: [60.],
            TEST_RETURN_TEMP_COL: [72.],
            TEST_OUT_TEMP_COL: [45.],
            TEST_SUPPLY_VFD_SPEED_COL: [.8],
        }
        return pd.DataFrame(data)

    def test_no_fault(self):
        results = fc2.apply(self.no_fault_df())
        actual = results.loc[0, 'fc2_flag']
        expected = 0.0
        message = f"fc2 no_fault_df actual is {actual} and expected is {expected}"
        assert actual == expected, message


class TestFault(object):

    def fault_df(self) -> pd.DataFrame:
        data = {
            TEST_MIX_TEMP_COL: [45.],
            TEST_RETURN_TEMP_COL: [72.],
            TEST_OUT_TEMP_COL: [60.],
            TEST_SUPPLY_VFD_SPEED_COL: [.8],
        }
        return pd.DataFrame(data)

    def test_fault(self):
        results = fc2.apply(self.fault_df())
        actual = results.loc[0, 'fc2_flag']
        expected = 1.0
        message = f"fc2 fault_df actual is {actual} and expected is {expected}"
        assert actual == expected, message


class TestFaultOnInt(object):

    def fault_df_on_output_int(self) -> pd.DataFrame:
        data = {
            TEST_MIX_TEMP_COL: [45.],
            TEST_RETURN_TEMP_COL: [72.],
            TEST_OUT_TEMP_COL: [60.],
            TEST_SUPPLY_VFD_SPEED_COL: [88],
        }
        return pd.DataFrame(data)

    def test_fault_on_int(self):
        with pytest.raises(TypeError, 
                           match=HelperUtils().float_int_check_err(TEST_SUPPLY_VFD_SPEED_COL)):
            fc2.apply(self.fault_df_on_output_int())


class TestFaultOnFloatGreaterThanOne(object):

    def fault_df_on_output_greater_than_one(self) -> pd.DataFrame:
        data = {
            TEST_MIX_TEMP_COL: [45.],
            TEST_RETURN_TEMP_COL: [72.],
            TEST_OUT_TEMP_COL: [60.],
            TEST_SUPPLY_VFD_SPEED_COL: [88.8],
        }
        return pd.DataFrame(data)

    def test_fault_on_float_greater_than_one(self):
        with pytest.raises(TypeError,
                           match=HelperUtils().float_max_check_err(TEST_SUPPLY_VFD_SPEED_COL)):
            fc2.apply(self.fault_df_on_output_greater_than_one())
