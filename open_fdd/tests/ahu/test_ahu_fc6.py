import pandas as pd
import pytest
from open_fdd.air_handling_unit.faults import FaultConditionSix
from open_fdd.air_handling_unit.faults.helper_utils import HelperUtils

"""
To see print statements in pytest run with:
$ py -3.12 -m pytest tests/ahu/test_ahu_fc6.py -rP -s

OA FRACTION TOO LOW OR TOO HIGH; SHOULD BE EQUAL TO %OAmin
"""

# Constants
TEST_AIRFLOW_ERR_THRES = 0.3
TEST_AHU_MIN_CFM_DESIGN = 3000.0
TEST_OAT_DEGF_ERR_THRES = 5.0
TEST_RAT_DEGF_ERR_THRES = 2.0
TEST_DELTA_TEMP_MIN = 10.0
TEST_AHU_MIN_OA_DPR = 0.2
TEST_VAV_TOTAL_AIR_FLOW_COL = "vav_total_air_flow"
TEST_MIX_TEMP_COL = "mix_air_temp"
TEST_OUT_TEMP_COL = "out_air_temp"
TEST_RETURN_TEMP_COL = "return_air_temp"
TEST_SUPPLY_VFD_SPEED_COL = "fan_vfd_speed_col"
TEST_MIX_AIR_DAMPER_COL = "economizer_sig_col"
TEST_HEATING_COIL_SIG_COL = "heating_sig_col"
TEST_COOLING_COIL_SIG_COL = "cooling_sig_col"
ROLLING_WINDOW_SIZE = 5

# Initialize FaultConditionSix with a dictionary
fault_condition_params = {
    "AIRFLOW_ERR_THRES": TEST_AIRFLOW_ERR_THRES,
    "AHU_MIN_OA_CFM_DESIGN": TEST_AHU_MIN_CFM_DESIGN,
    "OUTDOOR_DEGF_ERR_THRES": TEST_OAT_DEGF_ERR_THRES,
    "RETURN_DEGF_ERR_THRES": TEST_RAT_DEGF_ERR_THRES,
    "OAT_RAT_DELTA_MIN": TEST_DELTA_TEMP_MIN,
    "AHU_MIN_OA_DPR": TEST_AHU_MIN_OA_DPR,
    "SUPPLY_FAN_AIR_VOLUME_COL": TEST_VAV_TOTAL_AIR_FLOW_COL,
    "MAT_COL": TEST_MIX_TEMP_COL,
    "OAT_COL": TEST_OUT_TEMP_COL,
    "RAT_COL": TEST_RETURN_TEMP_COL,
    "SUPPLY_VFD_SPEED_COL": TEST_SUPPLY_VFD_SPEED_COL,
    "ECONOMIZER_SIG_COL": TEST_MIX_AIR_DAMPER_COL,
    "HEATING_SIG_COL": TEST_HEATING_COIL_SIG_COL,
    "COOLING_SIG_COL": TEST_COOLING_COIL_SIG_COL,
    "TROUBLESHOOT_MODE": False,  # default value
    "ROLLING_WINDOW_SIZE": ROLLING_WINDOW_SIZE,  # rolling sum window size
}

fc6 = FaultConditionSix(fault_condition_params)


class TestNoFaultNoHtg(object):

    def no_fault_df_no_htg(self) -> pd.DataFrame:
        data = {
            TEST_VAV_TOTAL_AIR_FLOW_COL: [10000, 10050, 10025, 10075, 10030, 10020],
            TEST_MIX_TEMP_COL: [55, 56, 55.5, 56.5, 55.2, 55.8],
            TEST_OUT_TEMP_COL: [10, 10.5, 10.2, 10.8, 10.3, 10.1],
            TEST_RETURN_TEMP_COL: [72, 72.5, 72.2, 72.8, 72.3, 72.1],
            TEST_SUPPLY_VFD_SPEED_COL: [0.66, 0.67, 0.65, 0.66, 0.68, 0.67],
            TEST_MIX_AIR_DAMPER_COL: [TEST_AHU_MIN_OA_DPR] * 6,
            TEST_HEATING_COIL_SIG_COL: [0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
            TEST_COOLING_COIL_SIG_COL: [0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
        }
        return pd.DataFrame(data)

    def test_no_fault_no_htg(self):
        results = fc6.apply(self.no_fault_df_no_htg())
        actual = results["fc6_flag"].sum()
        expected = 0
        message = (
            f"FC6 no_fault_df_no_htg actual is {actual} and expected is {expected}"
        )
        assert actual == expected, message


class TestFaultInHtg(object):

    def fault_df_in_htg(self) -> pd.DataFrame:
        data = {
            TEST_VAV_TOTAL_AIR_FLOW_COL: [10000, 10050, 10025, 10075, 10030, 10020],
            TEST_MIX_TEMP_COL: [30, 29.5, 30.5, 29.8, 30.2, 29.6],
            TEST_OUT_TEMP_COL: [10, 10.5, 10.2, 10.8, 10.3, 10.1],
            TEST_RETURN_TEMP_COL: [72, 72.5, 72.2, 72.8, 72.3, 72.1],
            TEST_SUPPLY_VFD_SPEED_COL: [0.66, 0.67, 0.65, 0.66, 0.68, 0.67],
            TEST_MIX_AIR_DAMPER_COL: [TEST_AHU_MIN_OA_DPR] * 6,
            TEST_HEATING_COIL_SIG_COL: [0.66, 0.67, 0.65, 0.66, 0.68, 0.67],
            TEST_COOLING_COIL_SIG_COL: [0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
        }
        return pd.DataFrame(data)

    def test_fault_in_htg(self):
        results = fc6.apply(self.fault_df_in_htg())
        actual = results["fc6_flag"].sum()
        expected = 2
        message = f"FC6 fault_df_in_htg actual is {actual} and expected is {expected}"
        assert actual == expected, message


class TestNoFaultInEconMode(object):

    def no_fault_df_in_econ(self) -> pd.DataFrame:
        data = {
            TEST_VAV_TOTAL_AIR_FLOW_COL: [10000, 10050, 10025, 10075, 10030, 10020],
            TEST_MIX_TEMP_COL: [90, 91, 89.5, 91.2, 90.5, 91.1],
            TEST_OUT_TEMP_COL: [110, 110.5, 110.2, 110.8, 110.3, 110.1],
            TEST_RETURN_TEMP_COL: [72, 72.5, 72.2, 72.8, 72.3, 72.1],
            TEST_SUPPLY_VFD_SPEED_COL: [0.66, 0.67, 0.65, 0.66, 0.68, 0.67],
            TEST_MIX_AIR_DAMPER_COL: [0.99, 0.98, 0.97, 0.99, 0.98, 0.99],
            TEST_HEATING_COIL_SIG_COL: [0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
            TEST_COOLING_COIL_SIG_COL: [0.50, 0.51, 0.49, 0.52, 0.50, 0.51],
        }
        return pd.DataFrame(data)

    def test_no_fault_in_econ_mode(self):
        results = fc6.apply(self.no_fault_df_in_econ())
        actual = results["fc6_flag"].sum()
        expected = 0
        message = (
            f"FC6 no_fault_df_in_econ actual is {actual} and expected is {expected}"
        )
        assert actual == expected, message


class TestNoFaultInEconPlusMechClg(object):

    def no_fault_df_in_econ_plus_mech(self) -> pd.DataFrame:
        data = {
            TEST_VAV_TOTAL_AIR_FLOW_COL: [10000, 10050, 10025, 10075, 10030, 10020],
            TEST_MIX_TEMP_COL: [55, 56, 55.5, 56.5, 55.2, 55.8],
            TEST_OUT_TEMP_COL: [10, 10.5, 10.2, 10.8, 10.3, 10.1],
            TEST_RETURN_TEMP_COL: [72, 72.5, 72.2, 72.8, 72.3, 72.1],
            TEST_SUPPLY_VFD_SPEED_COL: [0.66, 0.67, 0.65, 0.66, 0.68, 0.67],
            TEST_MIX_AIR_DAMPER_COL: [0.66, 0.67, 0.65, 0.66, 0.68, 0.67],
            TEST_HEATING_COIL_SIG_COL: [0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
            TEST_COOLING_COIL_SIG_COL: [0.5, 0.51, 0.49, 0.52, 0.50, 0.51],
        }
        return pd.DataFrame(data)

    def test_no_fault_in_econ_plus_mech_mode(self):
        results = fc6.apply(self.no_fault_df_in_econ_plus_mech())
        actual = results["fc6_flag"].sum()
        expected = 0
        message = f"FC6 no_fault_df_in_econ_plus_mech actual is {actual} and expected is {expected}"
        assert actual == expected, message


class TestFaultInMechClg(object):

    def fault_df_in_mech_clg(self) -> pd.DataFrame:
        data = {
            TEST_VAV_TOTAL_AIR_FLOW_COL: [10000, 10050, 10025, 10075, 10030, 10020],
            TEST_MIX_TEMP_COL: [30, 30.5, 30, 30.5, 30.8, 30.2],
            TEST_OUT_TEMP_COL: [5.2, 5.5, 5.2, 5.8, 5.3, 5.1],
            TEST_RETURN_TEMP_COL: [72, 72.5, 72.2, 72.8, 72.3, 72.1],
            TEST_SUPPLY_VFD_SPEED_COL: [0.66, 0.67, 0.65, 0.66, 0.68, 0.67],
            TEST_MIX_AIR_DAMPER_COL: [TEST_AHU_MIN_OA_DPR] * 6,
            TEST_HEATING_COIL_SIG_COL: [0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
            TEST_COOLING_COIL_SIG_COL: [0.50, 0.51, 0.49, 0.52, 0.50, 0.51],
        }
        return pd.DataFrame(data)

    def test_fault_in_mech_mode(self):
        results = fc6.apply(self.fault_df_in_mech_clg())
        actual = results["fc6_flag"].sum()
        expected = 2
        message = (
            f"FC6 fault_df_in_mech_clg actual is {actual} and expected is {expected}"
        )
        assert actual == expected, message


class TestNoFaultInMechClg(object):

    def no_fault_df_in_mech_clg(self) -> pd.DataFrame:
        data = {
            TEST_VAV_TOTAL_AIR_FLOW_COL: [10000, 10050, 10025, 10075, 10030, 10020],
            TEST_MIX_TEMP_COL: [60, 60.5, 60, 60.5, 60.8, 60.2],
            TEST_OUT_TEMP_COL: [5.2, 5.5, 5.2, 5.8, 5.3, 5.1],
            TEST_RETURN_TEMP_COL: [72, 72.5, 72.2, 72.8, 72.3, 72.1],
            TEST_SUPPLY_VFD_SPEED_COL: [0.66, 0.67, 0.65, 0.66, 0.68, 0.67],
            TEST_MIX_AIR_DAMPER_COL: [TEST_AHU_MIN_OA_DPR] * 6,
            TEST_HEATING_COIL_SIG_COL: [0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
            TEST_COOLING_COIL_SIG_COL: [0.50, 0.51, 0.49, 0.52, 0.50, 0.51],
        }
        return pd.DataFrame(data)

    def test_no_fault_in_mech_mode(self):
        results = fc6.apply(self.no_fault_df_in_mech_clg())
        actual = results["fc6_flag"].sum()
        expected = 0
        message = (
            f"FC6 no_fault_df_in_mech_clg actual is {actual} and expected is {expected}"
        )
        assert actual == expected, message


class TestFaultOnInt(object):

    def fault_df_on_output_int(self) -> pd.DataFrame:
        data = {
            TEST_VAV_TOTAL_AIR_FLOW_COL: [10000, 10050, 10025, 10075, 10030, 10020],
            TEST_MIX_TEMP_COL: [80, 80.5, 81, 80.8, 81.2, 80.3],
            TEST_OUT_TEMP_COL: [110, 110.5, 110.2, 110.8, 110.3, 110.1],
            TEST_RETURN_TEMP_COL: [72, 72.5, 72.2, 72.8, 72.3, 72.1],
            TEST_SUPPLY_VFD_SPEED_COL: [66, 67, 65, 66, 68, 67],
            TEST_MIX_AIR_DAMPER_COL: [TEST_AHU_MIN_OA_DPR] * 6,
            TEST_HEATING_COIL_SIG_COL: [0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
            TEST_COOLING_COIL_SIG_COL: [0.50, 0.51, 0.49, 0.52, 0.50, 0.51],
        }
        return pd.DataFrame(data)

    def test_fault_on_int(self):
        with pytest.raises(
            TypeError,
            match=HelperUtils().float_int_check_err(TEST_SUPPLY_VFD_SPEED_COL),
        ):
            fc6.apply(self.fault_df_on_output_int())


class TestFaultOnFloatGreaterThanOne(object):

    def fault_df_on_output_greater_than_one(self) -> pd.DataFrame:
        data = {
            TEST_VAV_TOTAL_AIR_FLOW_COL: [10000, 10050, 10025, 10075, 10030, 10020],
            TEST_MIX_TEMP_COL: [80, 80.5, 81, 80.8, 81.2, 80.3],
            TEST_OUT_TEMP_COL: [110, 110.5, 110.2, 110.8, 110.3, 110.1],
            TEST_RETURN_TEMP_COL: [72, 72.5, 72.2, 72.8, 72.3, 72.1],
            TEST_SUPPLY_VFD_SPEED_COL: [1.1, 1.2, 1.3, 1.1, 1.2, 1.1],
            TEST_MIX_AIR_DAMPER_COL: [TEST_AHU_MIN_OA_DPR] * 6,
            TEST_HEATING_COIL_SIG_COL: [0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
            TEST_COOLING_COIL_SIG_COL: [0.50, 0.51, 0.49, 0.52, 0.50, 0.51],
        }
        return pd.DataFrame(data)

    def test_fault_on_float_greater_than_one(self):
        with pytest.raises(
            TypeError,
            match=HelperUtils().float_max_check_err(TEST_SUPPLY_VFD_SPEED_COL),
        ):
            fc6.apply(self.fault_df_on_output_greater_than_one())


if __name__ == "__main__":
    pytest.main()
