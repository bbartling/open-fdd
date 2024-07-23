from faults import FaultConditionFourteen, HelperUtils
import pandas as pd
import pytest

'''
to see print statements in pytest run with
$ pytest tests/unit/test_ahu_fc14.py -rP

Temp drop across innactive clg coil in OS1 & OS2
'''

TEST_DELTA_SUPPLY_FAN = 2
TEST_COIL_TEMP_ENTER_ERR_THRES = 1
TEST_COIL_TEMP_LEAVE_ERR_THRES = 1
TEST_AHU_MIN_OA_DPR = .2
TEST_CLG_COIL_ENTER_TEMP_COL = "clg_enter_air_temp"
TEST_CLG_COIL_LEAVE_TEMP_COL = "clg_leave_air_temp"
TEST_CLG_COIL_CMD_COL = "cooling_sig_col"
TEST_HTG_COIL_CMD_COL = "heating_sig_col"
TEST_MIX_AIR_DAMPER_COL = "economizer_sig_col"
TEST_SUPPLY_VFD_SPEED_COL = "supply_vfd_speed"

        
fc14 = FaultConditionFourteen(
    TEST_DELTA_SUPPLY_FAN,
    TEST_COIL_TEMP_ENTER_ERR_THRES,
    TEST_COIL_TEMP_LEAVE_ERR_THRES,
    TEST_AHU_MIN_OA_DPR,
    TEST_CLG_COIL_ENTER_TEMP_COL,
    TEST_CLG_COIL_LEAVE_TEMP_COL,
    TEST_CLG_COIL_CMD_COL,
    TEST_HTG_COIL_CMD_COL,
    TEST_MIX_AIR_DAMPER_COL,
    TEST_SUPPLY_VFD_SPEED_COL
)


class TestNoFaultEcon(object):

    def no_fault_df_econ(self) -> pd.DataFrame:
        data = {
            TEST_CLG_COIL_ENTER_TEMP_COL: [55],
            TEST_CLG_COIL_LEAVE_TEMP_COL: [56.5],
            TEST_CLG_COIL_CMD_COL: [.0],
            TEST_HTG_COIL_CMD_COL: [.0],
            TEST_MIX_AIR_DAMPER_COL: [.55],
            TEST_SUPPLY_VFD_SPEED_COL: [.55]
        }
        return pd.DataFrame(data)

    def test_no_fault_econ(self):
        results = fc14.apply(self.no_fault_df_econ())
        actual = results.loc[0, 'fc14_flag']
        expected = 0.0
        message = f"fc14 no_fault_df_econ actual is {actual} and expected is {expected}"
        assert actual == expected, message
        

class TestNoFaultHtg(object):

    def no_fault_df_htg(self) -> pd.DataFrame:
        data = {
            TEST_CLG_COIL_ENTER_TEMP_COL: [55],
            TEST_CLG_COIL_LEAVE_TEMP_COL: [56.5],
            TEST_CLG_COIL_CMD_COL: [.0],
            TEST_HTG_COIL_CMD_COL: [.55],
            TEST_MIX_AIR_DAMPER_COL: [TEST_AHU_MIN_OA_DPR],
            TEST_SUPPLY_VFD_SPEED_COL: [.55]
        }
        return pd.DataFrame(data)

    def test_no_fault_htg(self):
        results = fc14.apply(self.no_fault_df_htg())
        actual = results.loc[0, 'fc14_flag']
        expected = 0.0
        message = f"fc14 no_fault_df_htg actual is {actual} and expected is {expected}"
        assert actual == expected, message


class TestFaultInEcon(object):

    def fault_df_in_econ(self) -> pd.DataFrame:
        data = {
            TEST_CLG_COIL_ENTER_TEMP_COL: [55],
            TEST_CLG_COIL_LEAVE_TEMP_COL: [50.5],
            TEST_CLG_COIL_CMD_COL: [.0],
            TEST_HTG_COIL_CMD_COL: [.0],
            TEST_MIX_AIR_DAMPER_COL: [.55],
            TEST_SUPPLY_VFD_SPEED_COL: [.55]
        }
        return pd.DataFrame(data)

    def test_fault_in_econ(self):
        results = fc14.apply(self.fault_df_in_econ())
        actual = results.loc[0, 'fc14_flag']
        expected = 1.0
        message = f"fc14 fault_df_in_econ actual is {actual} and expected is {expected}"
        assert actual == expected, message
        
        
class TestFaultInHtg(object):

    def fault_df_in_htg(self) -> pd.DataFrame:
        data = {
            TEST_CLG_COIL_ENTER_TEMP_COL: [55],
            TEST_CLG_COIL_LEAVE_TEMP_COL: [50.5],
            TEST_CLG_COIL_CMD_COL: [.0],
            TEST_HTG_COIL_CMD_COL: [.55],
            TEST_MIX_AIR_DAMPER_COL: [TEST_AHU_MIN_OA_DPR],
            TEST_SUPPLY_VFD_SPEED_COL: [.55]
        }
        return pd.DataFrame(data)

    def test_fault_in_htg(self):
        results = fc14.apply(self.fault_df_in_htg())
        actual = results.loc[0, 'fc14_flag']
        expected = 1.0
        message = f"fc14 fault_df_in_htg actual is {actual} and expected is {expected}"
        assert actual == expected, message
        



class TestFaultOnInt(object):

    def fault_df_on_output_int(self) -> pd.DataFrame:
        data = {
            TEST_CLG_COIL_ENTER_TEMP_COL: [55],
            TEST_CLG_COIL_LEAVE_TEMP_COL: [50.5],
            TEST_CLG_COIL_CMD_COL: [.0],
            TEST_HTG_COIL_CMD_COL: [.55],
            TEST_MIX_AIR_DAMPER_COL: [55],
            TEST_SUPPLY_VFD_SPEED_COL: [.55]
        }
        return pd.DataFrame(data)

    def test_fault_on_int(self):
        with pytest.raises(TypeError, 
                           match=HelperUtils().float_int_check_err(TEST_MIX_AIR_DAMPER_COL)):
            fc14.apply(self.fault_df_on_output_int())


class TestFaultOnFloatGreaterThanOne(object):

    def fault_df_on_output_greater_than_one(self) -> pd.DataFrame:
        data = {
            TEST_CLG_COIL_ENTER_TEMP_COL: [55],
            TEST_CLG_COIL_LEAVE_TEMP_COL: [50.5],
            TEST_CLG_COIL_CMD_COL: [.0],
            TEST_HTG_COIL_CMD_COL: [.55],
            TEST_MIX_AIR_DAMPER_COL: [55.5],
            TEST_SUPPLY_VFD_SPEED_COL: [.55]
        }
        return pd.DataFrame(data)

    def test_fault_on_float_greater_than_one(self):
        with pytest.raises(TypeError,
                           match=HelperUtils().float_max_check_err(TEST_MIX_AIR_DAMPER_COL)):
            fc14.apply(self.fault_df_on_output_greater_than_one())
            
