from faults import FaultConditionEight, HelperUtils
import pandas as pd
import pytest

'''
to see print statements in pytest run with
$ pytest tests/unit/test_ahu_fc8.py -rP

SAT and MAT should be approx equal in ECON mode only
'''

TEST_DELTA_SUPPLY_FAN = 2
TEST_MIX_DEGF_ERR_THRES = 2
TEST_SUPPLY_DEGF_ERR_THRES = 2
TEST_AHU_MIN_OA_DPR = .2
TEST_MIX_TEMP_COL = "mix_air_temp"
TEST_SAT_COL = "supply_air_temp"
TEST_MIX_AIR_DAMPER_COL = "economizer_sig_col"
TEST_COOLING_COIL_SIG_COL = "cooling_sig_col"


fc8 = FaultConditionEight(
    TEST_DELTA_SUPPLY_FAN,
    TEST_MIX_DEGF_ERR_THRES,
    TEST_SUPPLY_DEGF_ERR_THRES,
    TEST_AHU_MIN_OA_DPR,
    TEST_MIX_TEMP_COL,
    TEST_SAT_COL,
    TEST_MIX_AIR_DAMPER_COL,
    TEST_COOLING_COIL_SIG_COL,
)


class TestNoFaultNoEcon(object):

    def no_fault_df_no_econ(self) -> pd.DataFrame:
        data = {
            TEST_MIX_TEMP_COL: [55],
            TEST_SAT_COL: [59],
            TEST_MIX_AIR_DAMPER_COL: [.80],
            TEST_COOLING_COIL_SIG_COL: [.80],
        }
        return pd.DataFrame(data)

    def test_no_fault_no_econ(self):
        results = fc8.apply(self.no_fault_df_no_econ())
        actual = results.loc[0, 'fc8_flag']
        expected = 0.0
        message = f"fc8 no_fault_df_no_econ actual is {actual} and expected is {expected}"
        assert actual == expected, message


class TestFaultInecon(object):

    def fault_df_in_econ(self) -> pd.DataFrame:
        data = {
            TEST_MIX_TEMP_COL: [55],
            TEST_SAT_COL: [60],
            TEST_MIX_AIR_DAMPER_COL: [.80],
            TEST_COOLING_COIL_SIG_COL: [.0],
        }
        return pd.DataFrame(data)

    def test_fault_in_econ(self):
        results = fc8.apply(self.fault_df_in_econ())
        actual = results.loc[0, 'fc8_flag']
        expected = 1.0
        message = f"fc8 fault_df_in_econ actual is {actual} and expected is {expected}"
        assert actual == expected, message



class TestFaultOnInt(object):

    def fault_df_on_output_int(self) -> pd.DataFrame:
        data = {
            TEST_MIX_TEMP_COL: [55],
            TEST_SAT_COL: [59],
            TEST_MIX_AIR_DAMPER_COL: [.80],
            TEST_COOLING_COIL_SIG_COL: [11],
        }
        return pd.DataFrame(data)

    def test_fault_on_int(self):
        with pytest.raises(TypeError, 
                           match=HelperUtils().float_int_check_err(TEST_COOLING_COIL_SIG_COL)):
            fc8.apply(self.fault_df_on_output_int())


class TestFaultOnFloatGreaterThanOne(object):

    def fault_df_on_output_greater_than_one(self) -> pd.DataFrame:
        data = {
            TEST_MIX_TEMP_COL: [55],
            TEST_SAT_COL: [59],
            TEST_MIX_AIR_DAMPER_COL: [.80],
            TEST_COOLING_COIL_SIG_COL: [11.1],
        }
        return pd.DataFrame(data)

    def test_fault_on_float_greater_than_one(self):
        with pytest.raises(TypeError,
                           match=HelperUtils().float_max_check_err(TEST_COOLING_COIL_SIG_COL)):
            fc8.apply(self.fault_df_on_output_greater_than_one())
            
