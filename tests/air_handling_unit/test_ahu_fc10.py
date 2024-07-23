from faults import FaultConditionTen, HelperUtils
import pandas as pd
import pytest

'''
to see print statements in pytest run with
$ pytest tests/unit/test_ahu_fc10.py -rP

SAT and MAT should be approx equal in OS3
'''


TEST_OAT_DEGF_ERR_THRES = 5
TEST_MIX_DEGF_ERR_THRES = 2
TEST_OAT_COL = "out_air_temp"
TEST_MAT_COL = "mix_air_temp"
TEST_COOLING_COIL_SIG_COL = "cooling_sig_col"
TEST_MIX_AIR_DAMPER_COL = "economizer_sig_col"


fc10 = FaultConditionTen(
    TEST_OAT_DEGF_ERR_THRES,
    TEST_MIX_DEGF_ERR_THRES,
    TEST_OAT_COL,
    TEST_MAT_COL,
    TEST_COOLING_COIL_SIG_COL,
    TEST_MIX_AIR_DAMPER_COL,
)


class TestNoFaultNoEcon(object):

    def no_fault_df_no_econ(self) -> pd.DataFrame:
        data = {
            TEST_MAT_COL: [55],
            TEST_OAT_COL: [56],
            TEST_COOLING_COIL_SIG_COL: [.11],
            TEST_MIX_AIR_DAMPER_COL: [.99],
        }
        return pd.DataFrame(data)

    def test_no_fault_no_econ(self):
        results = fc10.apply(self.no_fault_df_no_econ())
        actual = results.loc[0, 'fc10_flag']
        expected = 0.0
        message = f"fc10 no_fault_df_no_econ actual is {actual} and expected is {expected}"
        assert actual == expected, message


class TestFaultInecon(object):

    def fault_df_in_econ(self) -> pd.DataFrame:
        data = {
            TEST_MAT_COL: [55],
            TEST_OAT_COL: [75],
            TEST_COOLING_COIL_SIG_COL: [.11],
            TEST_MIX_AIR_DAMPER_COL: [.99],
        }
        return pd.DataFrame(data)

    def test_fault_in_econ(self):
        results = fc10.apply(self.fault_df_in_econ())
        actual = results.loc[0, 'fc10_flag']
        expected = 1.0
        message = f"fc10 fault_df_in_econ actual is {actual} and expected is {expected}"
        assert actual == expected, message



class TestFaultOnInt(object):

    def fault_df_on_output_int(self) -> pd.DataFrame:
        data = {
            TEST_MAT_COL: [55],
            TEST_OAT_COL: [75],
            TEST_COOLING_COIL_SIG_COL: [11],
            TEST_MIX_AIR_DAMPER_COL: [.80],
        }
        return pd.DataFrame(data)

    def test_fault_on_int(self):
        with pytest.raises(TypeError, 
                           match=HelperUtils().float_int_check_err(TEST_COOLING_COIL_SIG_COL)):
            fc10.apply(self.fault_df_on_output_int())


class TestFaultOnFloatGreaterThanOne(object):

    def fault_df_on_output_greater_than_one(self) -> pd.DataFrame:
        data = {
            TEST_MAT_COL: [55],
            TEST_OAT_COL: [75],
            TEST_COOLING_COIL_SIG_COL: [11.0],
            TEST_MIX_AIR_DAMPER_COL: [.80],
        }
        return pd.DataFrame(data)

    def test_fault_on_float_greater_than_one(self):
        with pytest.raises(TypeError,
                           match=HelperUtils().float_max_check_err(TEST_COOLING_COIL_SIG_COL)):
            fc10.apply(self.fault_df_on_output_greater_than_one())
            
