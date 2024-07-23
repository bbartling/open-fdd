from faults import FaultConditionTwelve, HelperUtils
import pandas as pd
import pytest

'''
to see print statements in pytest run with
$ pytest tests/unit/test_ahu_fc12.py -rP

SAT too high should be less than MAT. OS3 & OS4
'''

TEST_DELTA_SUPPLY_FAN = 2
TEST_MIX_DEGF_ERR_THRES = 2
TEST_SUPPLY_DEGF_ERR_THRES = 2
TEST_AHU_MIN_OA_DPR = .2
TEST_SAT_COL = "supply_air_temp"
TEST_MAT_COL = "mix_air_temp"
TEST_COOLING_COIL_SIG_COL = "cooling_sig_col"
TEST_MIX_AIR_DAMPER_COL = "economizer_sig_col"


fc12 = FaultConditionTwelve(
    TEST_DELTA_SUPPLY_FAN,
    TEST_MIX_DEGF_ERR_THRES,
    TEST_SUPPLY_DEGF_ERR_THRES,
    TEST_AHU_MIN_OA_DPR,
    TEST_SAT_COL,
    TEST_MAT_COL,
    TEST_COOLING_COIL_SIG_COL,
    TEST_MIX_AIR_DAMPER_COL,
)


class TestNoFaultNoEcon(object):

    def no_fault_df_no_econ(self) -> pd.DataFrame:
        data = {
            TEST_SAT_COL: [55],
            TEST_MAT_COL: [56],
            TEST_COOLING_COIL_SIG_COL: [.0],
            TEST_MIX_AIR_DAMPER_COL: [TEST_AHU_MIN_OA_DPR],
        }
        return pd.DataFrame(data)

    def test_no_fault_no_econ(self):
        results = fc12.apply(self.no_fault_df_no_econ())
        actual = results.loc[0, 'fc12_flag']
        expected = 0.0
        message = f"fc12 no_fault_df_no_econ actual is {actual} and expected is {expected}"
        assert actual == expected, message


class TestFaultInEconPlusMech(object):

    def fault_df_in_econ_plus_mech(self) -> pd.DataFrame:
        data = {
            TEST_SAT_COL: [66],
            TEST_MAT_COL: [56],
            TEST_COOLING_COIL_SIG_COL: [.50],
            TEST_MIX_AIR_DAMPER_COL: [.99],
        }
        return pd.DataFrame(data)

    def test_fault_in_econ_plus_mech(self):
        results = fc12.apply(self.fault_df_in_econ_plus_mech())
        actual = results.loc[0, 'fc12_flag']
        expected = 1.0
        message = f"fc12 fault_df_in_econ actual is {actual} and expected is {expected}"
        assert actual == expected, message

class TestFaultInMechClg(object):

    def fault_df_in_mech_clg(self) -> pd.DataFrame:
        data = {
            TEST_SAT_COL: [66],
            TEST_MAT_COL: [56],
            TEST_COOLING_COIL_SIG_COL: [TEST_AHU_MIN_OA_DPR],
            TEST_MIX_AIR_DAMPER_COL: [.99],
        }
        return pd.DataFrame(data)

    def test_fault_in_econ_plus_mech(self):
        results = fc12.apply(self.fault_df_in_mech_clg())
        actual = results.loc[0, 'fc12_flag']
        expected = 1.0
        message = f"fc12 fault_df_in_econ actual is {actual} and expected is {expected}"
        assert actual == expected, message

class TestFaultOnInt(object):

    def fault_df_on_output_int(self) -> pd.DataFrame:
        data = {
            TEST_SAT_COL: [55],
            TEST_MAT_COL: [56],
            TEST_COOLING_COIL_SIG_COL: [.0],
            TEST_MIX_AIR_DAMPER_COL: [11],
        }
        return pd.DataFrame(data)

    def test_fault_on_int(self):
        with pytest.raises(TypeError, 
                           match=HelperUtils().float_int_check_err(TEST_MIX_AIR_DAMPER_COL)):
            fc12.apply(self.fault_df_on_output_int())


class TestFaultOnFloatGreaterThanOne(object):

    def fault_df_on_output_greater_than_one(self) -> pd.DataFrame:
        data = {
            TEST_SAT_COL: [55],
            TEST_MAT_COL: [56],
            TEST_COOLING_COIL_SIG_COL: [.0],
            TEST_MIX_AIR_DAMPER_COL: [11.1],
        }
        return pd.DataFrame(data)

    def test_fault_on_float_greater_than_one(self):
        with pytest.raises(TypeError,
                           match=HelperUtils().float_max_check_err(TEST_MIX_AIR_DAMPER_COL)):
            fc12.apply(self.fault_df_on_output_greater_than_one())
            
