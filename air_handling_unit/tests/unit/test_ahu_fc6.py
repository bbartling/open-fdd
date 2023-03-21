from faults import FaultConditionSix, HelperUtils
import pandas as pd
import pytest

'''
to see print statements in pytest run with
$ pytest tests/unit/test_ahu_fc6.py -rP

OA FRACTION TOO LOW OR TOO HIGH; SHOULD BE EQUAL TO %OAmin
'''


TEST_AIRFLOW_ERR_THRES = .3
TEST_AHU_MIN_CFM_DESIGN = 3000
TEST_OAT_DEGF_ERR_THRES = 5.
TEST_RAT_DEGF_ERR_THRES = 2.
TEST_DELTA_TEMP_MIN = 10.
TEST_AHU_MIN_OA_DPR = .2
TEST_VAV_TOTAL_AIR_FLOW_COL = 10000
TEST_MIX_TEMP_COL = "mix_air_temp"
TEST_OUT_TEMP_COL = "out_air_temp"
TEST_RETURN_TEMP_COL = "return_air_temp"
TEST_SUPPLY_VFD_SPEED_COL = "fan_vfd_speed_col"
TEST_MIX_AIR_DAMPER_COL = "economizer_sig_col"
TEST_HEATING_COIL_SIG_COL = "heating_sig_col"
TEST_COOLING_COIL_SIG_COL = "cooling_sig_col"


fc6 = FaultConditionSix(
    TEST_AIRFLOW_ERR_THRES,
    TEST_AHU_MIN_CFM_DESIGN,
    TEST_OAT_DEGF_ERR_THRES,
    TEST_RAT_DEGF_ERR_THRES,
    TEST_DELTA_TEMP_MIN,
    TEST_AHU_MIN_OA_DPR,
    TEST_VAV_TOTAL_AIR_FLOW_COL,
    TEST_MIX_TEMP_COL,
    TEST_OUT_TEMP_COL,
    TEST_RETURN_TEMP_COL,
    TEST_SUPPLY_VFD_SPEED_COL,
    TEST_MIX_AIR_DAMPER_COL,
    TEST_HEATING_COIL_SIG_COL,
    TEST_COOLING_COIL_SIG_COL,
)



class TestNoFaultNoHtg(object):

    def no_fault_df_no_htg(self) -> pd.DataFrame:
        data = {
            TEST_VAV_TOTAL_AIR_FLOW_COL: [10000],
            TEST_MIX_TEMP_COL: [55],
            TEST_OUT_TEMP_COL: [10],
            TEST_RETURN_TEMP_COL: [72],
            TEST_SUPPLY_VFD_SPEED_COL: [.66],
            TEST_MIX_AIR_DAMPER_COL: [TEST_AHU_MIN_OA_DPR],
            TEST_HEATING_COIL_SIG_COL: [0.],
            TEST_COOLING_COIL_SIG_COL: [0.],
        }
        return pd.DataFrame(data)

    def test_no_fault_no_htg(self):
        results = fc6.apply(self.no_fault_df_no_htg())
        actual = results.loc[0, 'fc6_flag']
        expected = 0.0
        message = f"fc6 no_fault_df_no_htg actual is {actual} and expected is {expected}"
        assert actual == expected, message


class TestFaultInHtg(object):

    def fault_df_in_htg(self) -> pd.DataFrame:
        data = {
            TEST_VAV_TOTAL_AIR_FLOW_COL: [10000],
            TEST_MIX_TEMP_COL: [30],
            TEST_OUT_TEMP_COL: [10],
            TEST_RETURN_TEMP_COL: [72],
            TEST_SUPPLY_VFD_SPEED_COL: [.66],
            TEST_MIX_AIR_DAMPER_COL: [TEST_AHU_MIN_OA_DPR],
            TEST_HEATING_COIL_SIG_COL: [.66],
            TEST_COOLING_COIL_SIG_COL: [0.],
        }
        return pd.DataFrame(data)

    def test_fault_in_htg(self):
        results = fc6.apply(self.fault_df_in_htg())
        actual = results.loc[0, 'fc6_flag']
        expected = 1.0
        message = f"fc6 fault_df_in_htg actual is {actual} and expected is {expected}"
        assert actual == expected, message


class TestNoFaultInEconMode(object):

    def no_fault_df_in_econ(self) -> pd.DataFrame:
        data = {
            TEST_VAV_TOTAL_AIR_FLOW_COL: [10000],
            TEST_MIX_TEMP_COL: [90],
            TEST_OUT_TEMP_COL: [110],
            TEST_RETURN_TEMP_COL: [72],
            TEST_SUPPLY_VFD_SPEED_COL: [.66],
            TEST_MIX_AIR_DAMPER_COL: [.99],
            TEST_HEATING_COIL_SIG_COL: [0.],
            TEST_COOLING_COIL_SIG_COL: [.50],
        }
        return pd.DataFrame(data)

    def test_no_fault_in_econ_mode(self):
        results = fc6.apply(self.no_fault_df_in_econ())
        actual = results.loc[0, 'fc6_flag']
        expected = 0.0
        message = f"fc6 no_fault_df_in_econ actual is {actual} and expected is {expected}"
        assert actual == expected, message


class TestNoFaultInEconPlusMechClg(object):

    def no_fault_df_in_econ_plus_mech(self) -> pd.DataFrame:
        data = {
            TEST_VAV_TOTAL_AIR_FLOW_COL: [10000],
            TEST_MIX_TEMP_COL: [55],
            TEST_OUT_TEMP_COL: [10],
            TEST_RETURN_TEMP_COL: [72],
            TEST_SUPPLY_VFD_SPEED_COL: [.66],
            TEST_MIX_AIR_DAMPER_COL: [.66],
            TEST_HEATING_COIL_SIG_COL: [0.],
            TEST_COOLING_COIL_SIG_COL: [0.5],
        }
        return pd.DataFrame(data)

    def test_no_fault_in_econ_plus_mech_mode(self):
        results = fc6.apply(self.no_fault_df_in_econ_plus_mech())
        actual = results.loc[0, 'fc6_flag']
        expected = 0.0
        message = f"fc6 no_fault_df_in_econ_plus_mech actual is {actual} and expected is {expected}"
        assert actual == expected, message


class TestFaultInMechClg(object):

    def fault_df_in_mech_clg(self) -> pd.DataFrame:
        data = {
            TEST_VAV_TOTAL_AIR_FLOW_COL: [10000],
            TEST_MIX_TEMP_COL: [95],
            TEST_OUT_TEMP_COL: [110],
            TEST_RETURN_TEMP_COL: [72],
            TEST_SUPPLY_VFD_SPEED_COL: [.66],
            TEST_MIX_AIR_DAMPER_COL: [TEST_AHU_MIN_OA_DPR],
            TEST_HEATING_COIL_SIG_COL: [0.],
            TEST_COOLING_COIL_SIG_COL: [.50],
        }
        return pd.DataFrame(data)

    def test_fault_in_mech_mode(self):
        results = fc6.apply(self.fault_df_in_mech_clg())
        actual = results.loc[0, 'fc6_flag']
        expected = 1.0
        message = f"fc6 fault_df_in_mech_clg actual is {actual} and expected is {expected}"
        assert actual == expected, message


class TestNoFaultInMechClg(object):

    def no_fault_df_in_mech_clg(self) -> pd.DataFrame:
        data = {
            TEST_VAV_TOTAL_AIR_FLOW_COL: [10000],
            TEST_MIX_TEMP_COL: [80],
            TEST_OUT_TEMP_COL: [110],
            TEST_RETURN_TEMP_COL: [72],
            TEST_SUPPLY_VFD_SPEED_COL: [.66],
            TEST_MIX_AIR_DAMPER_COL: [TEST_AHU_MIN_OA_DPR],
            TEST_HEATING_COIL_SIG_COL: [0.],
            TEST_COOLING_COIL_SIG_COL: [.50],
        }
        return pd.DataFrame(data)

    def test_no_fault_in_mech_mode(self):
        results = fc6.apply(self.no_fault_df_in_mech_clg())
        actual = results.loc[0, 'fc6_flag']
        expected = 0.0
        message = f"fc6 no_fault_df_in_mech_clg actual is {actual} and expected is {expected}"
        assert actual == expected, message



class TestFaultOnInt(object):

    def fault_df_on_output_int(self) -> pd.DataFrame:
        data = {
            TEST_VAV_TOTAL_AIR_FLOW_COL: [10000],
            TEST_MIX_TEMP_COL: [80],
            TEST_OUT_TEMP_COL: [110],
            TEST_RETURN_TEMP_COL: [72],
            TEST_SUPPLY_VFD_SPEED_COL: [66],
            TEST_MIX_AIR_DAMPER_COL: [TEST_AHU_MIN_OA_DPR],
            TEST_HEATING_COIL_SIG_COL: [0.],
            TEST_COOLING_COIL_SIG_COL: [.55],
        }
        return pd.DataFrame(data)

    def test_fault_on_int(self):
        with pytest.raises(TypeError, 
                           match=HelperUtils().float_int_check_err(TEST_SUPPLY_VFD_SPEED_COL)):
            fc6.apply(self.fault_df_on_output_int())


class TestFaultOnFloatGreaterThanOne(object):

    def fault_df_on_output_greater_than_one(self) -> pd.DataFrame:
        data = {
            TEST_VAV_TOTAL_AIR_FLOW_COL: [10000],
            TEST_MIX_TEMP_COL: [80],
            TEST_OUT_TEMP_COL: [110],
            TEST_RETURN_TEMP_COL: [72],
            TEST_SUPPLY_VFD_SPEED_COL: [66.66],
            TEST_MIX_AIR_DAMPER_COL: [TEST_AHU_MIN_OA_DPR],
            TEST_HEATING_COIL_SIG_COL: [0.],
            TEST_COOLING_COIL_SIG_COL: [.50],
        }
        return pd.DataFrame(data)

    def test_fault_on_float_greater_than_one(self):
        with pytest.raises(TypeError,
                           match=HelperUtils().float_max_check_err(TEST_SUPPLY_VFD_SPEED_COL)):
            fc6.apply(self.fault_df_on_output_greater_than_one())
            
