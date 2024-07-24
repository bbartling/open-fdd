from faults import FaultConditionSeven, HelperUtils
import pandas as pd
import pytest

'''
to see print statements in pytest run with
$ pytest tests/unit/test_ahu_fc7.py -rP

SAT too low in full heating valve 100% in OS1 mode only
'''


TEST_SAT_DEGF_ERR_THRES = 2
TEST_SAT_COL = "supply_air_temp"
TEST_SAT_SP_COL = "supply_setpoint_air_temp"
TEST_HEATING_COIL_SIG_COL = "heating_sig_col"
TEST_SUPPLY_VFD_SPEED_COL = "fan_vfd_speed_col"



fc7 = FaultConditionSeven(
    TEST_SAT_DEGF_ERR_THRES,
    TEST_SAT_COL,
    TEST_SAT_SP_COL,
    TEST_HEATING_COIL_SIG_COL,
    TEST_SUPPLY_VFD_SPEED_COL,
)


class TestNoFaultNoHtg(object):

    def no_fault_df_no_htg(self) -> pd.DataFrame:
        data = {
            TEST_SAT_COL: [60],
            TEST_SAT_SP_COL: [62.2],
            TEST_HEATING_COIL_SIG_COL: [0.0],
            TEST_SUPPLY_VFD_SPEED_COL: [0.55],
        }
        return pd.DataFrame(data)

    def test_no_fault_no_htg(self):
        results = fc7.apply(self.no_fault_df_no_htg())
        actual = results.loc[0, 'fc7_flag']
        expected = 0.0
        message = f"fc7 no_fault_df_no_htg actual is {actual} and expected is {expected}"
        assert actual == expected, message


class TestFaultInHtg(object):

    def fault_df_in_htg(self) -> pd.DataFrame:
        data = {
            TEST_SAT_COL: [60],
            TEST_SAT_SP_COL: [66.2],
            TEST_HEATING_COIL_SIG_COL: [1.0],
            TEST_SUPPLY_VFD_SPEED_COL: [0.2],
        }
        return pd.DataFrame(data)

    def test_fault_in_htg(self):
        results = fc7.apply(self.fault_df_in_htg())
        actual = results.loc[0, 'fc7_flag']
        expected = 1.0
        message = f"fc7 fault_df_in_htg actual is {actual} and expected is {expected}"
        assert actual == expected, message





class TestFaultOnInt(object):

    def fault_df_on_output_int(self) -> pd.DataFrame:
        data = {
            TEST_SAT_COL: [60],
            TEST_SAT_SP_COL: [80.2],
            TEST_HEATING_COIL_SIG_COL: [1.0],
            TEST_SUPPLY_VFD_SPEED_COL: [20],
        }
        return pd.DataFrame(data)

    def test_fault_on_int(self):
        with pytest.raises(TypeError, 
                           match=HelperUtils().float_int_check_err(TEST_SUPPLY_VFD_SPEED_COL)):
            fc7.apply(self.fault_df_on_output_int())


class TestFaultOnFloatGreaterThanOne(object):

    def fault_df_on_output_greater_than_one(self) -> pd.DataFrame:
        data = {
            TEST_SAT_COL: [60],
            TEST_SAT_SP_COL: [80.2],
            TEST_HEATING_COIL_SIG_COL: [1.0],
            TEST_SUPPLY_VFD_SPEED_COL: [22.2],
        }
        return pd.DataFrame(data)

    def test_fault_on_float_greater_than_one(self):
        with pytest.raises(TypeError,
                           match=HelperUtils().float_max_check_err(TEST_SUPPLY_VFD_SPEED_COL)):
            fc7.apply(self.fault_df_on_output_greater_than_one())
            
