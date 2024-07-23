from faults import FaultConditionFive, HelperUtils
import pandas as pd
import pytest

'''
to see print statements in pytest run with
$ pytest tests/unit/test_ahu_fc5.py -rP

SAT too low; should be higher than MAT in HTG MODE
'''

TEST_MIX_DEGF_ERR_THRES = 2.
TEST_SUPPLY_DEGF_ERR_THRES = 2.
TEST_DELTA_T_SUPPLY_FAN = 5.
TEST_MIX_TEMP_COL = "mix_air_temp"
TEST_SUPPLY_TEMP_COL = "supply_air_temp"
TEST_HEATING_COIL_SIG_COL = "heating_sig_col"
TEST_SUPPLY_VFD_SPEED_COL = "supply_vfd_speed"


fc5 = FaultConditionFive(
    TEST_MIX_DEGF_ERR_THRES,
    TEST_SUPPLY_DEGF_ERR_THRES,
    TEST_DELTA_T_SUPPLY_FAN,
    TEST_MIX_TEMP_COL,
    TEST_SUPPLY_TEMP_COL,
    TEST_HEATING_COIL_SIG_COL,
    TEST_SUPPLY_VFD_SPEED_COL
)


class TestNoFaultinHtg(object):

    def no_fault_df_in_htg(self) -> pd.DataFrame:
        data = {
            TEST_MIX_TEMP_COL: [40.],
            TEST_SUPPLY_TEMP_COL: [80.],
            TEST_HEATING_COIL_SIG_COL: [0.55],
            TEST_SUPPLY_VFD_SPEED_COL: [0.55],
        }
        return pd.DataFrame(data)

    def test_no_fault_in_htg(self):
        results = fc5.apply(self.no_fault_df_in_htg())
        actual = results.loc[0, 'fc5_flag']
        expected = 0.0
        message = f"fc5 no_fault_df_in_htg actual is {actual} and expected is {expected}"
        assert actual == expected, message


class TestFaultInHtg(object):

    def fault_df_in_htg(self) -> pd.DataFrame:
        data = {
            TEST_MIX_TEMP_COL: [80.],
            TEST_SUPPLY_TEMP_COL: [40.],
            TEST_HEATING_COIL_SIG_COL: [0.55],
            TEST_SUPPLY_VFD_SPEED_COL: [0.55],
        }
        return pd.DataFrame(data)

    def test_fault_in_htg(self):
        results = fc5.apply(self.fault_df_in_htg())
        actual = results.loc[0, 'fc5_flag']
        expected = 1.0
        message = f"fc5 fault_df_in_htg actual is {actual} and expected is {expected}"
        assert actual == expected, message


class TestNoFaultNoHtg(object):

    def no_fault_df_no_htg(self) -> pd.DataFrame:
        data = {
            TEST_MIX_TEMP_COL: [40.],
            TEST_SUPPLY_TEMP_COL: [80.],
            TEST_HEATING_COIL_SIG_COL: [0.0],
            TEST_SUPPLY_VFD_SPEED_COL: [0.55],
        }
        return pd.DataFrame(data)

    def test_no_fault_no_htg(self):
        results = fc5.apply(self.no_fault_df_no_htg())
        actual = results.loc[0, 'fc5_flag']
        expected = 0.0
        message = f"fc5 test_no_fault_no_htg actual is {actual} and expected is {expected}"
        assert actual == expected, message


class TestFaultNoHtg(object):

    def fault_df_no_htg(self) -> pd.DataFrame:
        data = {
            TEST_MIX_TEMP_COL: [80.],
            TEST_SUPPLY_TEMP_COL: [40.],
            TEST_HEATING_COIL_SIG_COL: [0.],
            TEST_SUPPLY_VFD_SPEED_COL: [0.55],
        }
        return pd.DataFrame(data)

    def test_fault_no_htg(self):
        results = fc5.apply(self.fault_df_no_htg())
        actual = results.loc[0, 'fc5_flag']
        expected = 1.0
        message = f"fc5 fault_df_no_htg actual is {actual} and expected is {expected}"
        assert actual != expected, message


class TestFaultOnInt(object):

    def fault_df_on_output_int(self) -> pd.DataFrame:
        data = {
            TEST_MIX_TEMP_COL: [80.],
            TEST_SUPPLY_TEMP_COL: [40.],
            TEST_HEATING_COIL_SIG_COL: [0.55],
            TEST_SUPPLY_VFD_SPEED_COL: [55],
        }
        return pd.DataFrame(data)

    def test_fault_on_int(self):
        with pytest.raises(TypeError, 
                           match=HelperUtils().float_int_check_err(TEST_SUPPLY_VFD_SPEED_COL)):
            fc5.apply(self.fault_df_on_output_int())


class TestFaultOnFloatGreaterThanOne(object):

    def fault_df_on_output_greater_than_one(self) -> pd.DataFrame:
        data = {
            TEST_MIX_TEMP_COL: [80.],
            TEST_SUPPLY_TEMP_COL: [40.],
            TEST_HEATING_COIL_SIG_COL: [0.55],
            TEST_SUPPLY_VFD_SPEED_COL: [55.0],
        }
        return pd.DataFrame(data)

    def test_fault_on_float_greater_than_one(self):
        with pytest.raises(TypeError,
                           match=HelperUtils().float_max_check_err(TEST_SUPPLY_VFD_SPEED_COL)):
            fc5.apply(self.fault_df_on_output_greater_than_one())
