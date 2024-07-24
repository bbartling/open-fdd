from faults import FaultConditionEleven, HelperUtils
import pandas as pd
import pytest

'''
to see print statements in pytest run with
$ pytest tests/unit/test_ahu_fc11.py -rP

OAT Temp too low for 100% cooling in OS3
'''

TEST_DELTA_SUPPLY_FAN = 2
TEST_OAT_DEGF_ERR_THRES = 5
TEST_SUPPLY_DEGF_ERR_THRES = 2
TEST_SAT_SP_COL = "supply_air_sp_temp"
TEST_OAT_COL = "out_air_temp"
TEST_COOLING_COIL_SIG_COL = "cooling_sig_col"
TEST_MIX_AIR_DAMPER_COL = "economizer_sig_col"


fc11 = FaultConditionEleven(
    TEST_DELTA_SUPPLY_FAN,
    TEST_OAT_DEGF_ERR_THRES,
    TEST_SUPPLY_DEGF_ERR_THRES,
    TEST_SAT_SP_COL,
    TEST_OAT_COL,
    TEST_COOLING_COIL_SIG_COL,
    TEST_MIX_AIR_DAMPER_COL,
)


class TestNoFaultNoEcon(object):

    def no_fault_df_no_econ(self) -> pd.DataFrame:
        data = {
            TEST_SAT_SP_COL: [55],
            TEST_OAT_COL: [56],
            TEST_COOLING_COIL_SIG_COL: [.11],
            TEST_MIX_AIR_DAMPER_COL: [.99],
        }
        return pd.DataFrame(data)

    def test_no_fault_no_econ(self):
        results = fc11.apply(self.no_fault_df_no_econ())
        actual = results.loc[0, 'fc11_flag']
        expected = 0.0
        message = f"fc11 no_fault_df_no_econ actual is {actual} and expected is {expected}"
        assert actual == expected, message


class TestFaultInecon(object):

    def fault_df_in_econ(self) -> pd.DataFrame:
        data = {
            TEST_SAT_SP_COL: [55],
            TEST_OAT_COL: [44],
            TEST_COOLING_COIL_SIG_COL: [.11],
            TEST_MIX_AIR_DAMPER_COL: [.99],
        }
        return pd.DataFrame(data)

    def test_fault_in_econ(self):
        results = fc11.apply(self.fault_df_in_econ())
        actual = results.loc[0, 'fc11_flag']
        expected = 1.0
        message = f"fc11 fault_df_in_econ actual is {actual} and expected is {expected}"
        assert actual == expected, message



class TestFaultOnInt(object):

    def fault_df_on_output_int(self) -> pd.DataFrame:
        data = {
            TEST_SAT_SP_COL: [55],
            TEST_OAT_COL: [75],
            TEST_COOLING_COIL_SIG_COL: [11],
            TEST_MIX_AIR_DAMPER_COL: [.80],
        }
        return pd.DataFrame(data)

    def test_fault_on_int(self):
        with pytest.raises(TypeError, 
                           match=HelperUtils().float_int_check_err(TEST_COOLING_COIL_SIG_COL)):
            fc11.apply(self.fault_df_on_output_int())


class TestFaultOnFloatGreaterThanOne(object):

    def fault_df_on_output_greater_than_one(self) -> pd.DataFrame:
        data = {
            TEST_SAT_SP_COL: [55],
            TEST_OAT_COL: [75],
            TEST_COOLING_COIL_SIG_COL: [11.0],
            TEST_MIX_AIR_DAMPER_COL: [.80],
        }
        return pd.DataFrame(data)

    def test_fault_on_float_greater_than_one(self):
        with pytest.raises(TypeError,
                           match=HelperUtils().float_max_check_err(TEST_COOLING_COIL_SIG_COL)):
            fc11.apply(self.fault_df_on_output_greater_than_one())
            
