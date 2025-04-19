from datetime import datetime, timezone

import pandas as pd
import pytest

from open_fdd.air_handling_unit.faults import FaultConditionFour
from open_fdd.air_handling_unit.faults.helper_utils import HelperUtils

"""
To see print statements in pytest run with:
$ py -3.12 -m pytest tests/ahu/test_ahu_fc4.py -rP -s

Too much hunting in control system
OS state changes greater than 7 in an hour
"""

# Constants
DELTA_OS_MAX = 7
AHU_MIN_OA = 0.20
TEST_MIX_AIR_DAMPER_COL = "economizer_sig_col"
TEST_HEATING_COIL_SIG_COL = "heating_sig_col"
TEST_COOLING_COIL_SIG_COL = "cooling_sig_col"
TEST_SUPPLY_VFD_SPEED_COL = "fan_vfd_speed_col"
TEST_DATASET_ROWS = 60

# Initialize FaultConditionFour with a dictionary
fault_condition_params = {
    "DELTA_OS_MAX": DELTA_OS_MAX,
    "AHU_MIN_OA_DPR": AHU_MIN_OA,
    "ECONOMIZER_SIG_COL": TEST_MIX_AIR_DAMPER_COL,
    "HEATING_SIG_COL": TEST_HEATING_COIL_SIG_COL,
    "COOLING_SIG_COL": TEST_COOLING_COIL_SIG_COL,
    "SUPPLY_VFD_SPEED_COL": TEST_SUPPLY_VFD_SPEED_COL,
    "TROUBLESHOOT_MODE": False,  # default value
}

fc4 = FaultConditionFour(fault_condition_params)


def generate_timestamp() -> pd.Series:
    df = pd.DataFrame()
    date_range = pd.period_range(
        # make a time stamp starting at top of
        # the hour with one min intervals
        start=datetime(2022, 6, 6, 14, 30, 0, 0, tzinfo=timezone.utc),
        periods=TEST_DATASET_ROWS,
        freq="min",
    )
    df["Date"] = [x.to_timestamp() for x in date_range]
    return df["Date"]


def econ_plus_mech_clg_row() -> dict:
    data = {
        TEST_MIX_AIR_DAMPER_COL: 0.6,
        TEST_HEATING_COIL_SIG_COL: 0.0,
        TEST_COOLING_COIL_SIG_COL: 0.6,
        TEST_SUPPLY_VFD_SPEED_COL: 0.8,
    }
    return data


def mech_clg_row() -> dict:
    data = {
        TEST_MIX_AIR_DAMPER_COL: 0.0,
        TEST_HEATING_COIL_SIG_COL: 0.0,
        TEST_COOLING_COIL_SIG_COL: 0.6,
        TEST_SUPPLY_VFD_SPEED_COL: 0.8,
    }
    return data


def econ_plus_mech_clg_row_int() -> dict:
    data = {
        TEST_MIX_AIR_DAMPER_COL: 0.6,
        TEST_HEATING_COIL_SIG_COL: 0.0,
        TEST_COOLING_COIL_SIG_COL: 0.6,
        TEST_SUPPLY_VFD_SPEED_COL: 88,
    }
    return data


def econ_plus_mech_clg_row_float_greater_than_one() -> dict:
    data = {
        TEST_MIX_AIR_DAMPER_COL: 0.6,
        TEST_HEATING_COIL_SIG_COL: 0.0,
        TEST_COOLING_COIL_SIG_COL: 0.6,
        TEST_SUPPLY_VFD_SPEED_COL: 88.8,
    }
    return data


class TestFault(object):

    def fault_df(self) -> pd.DataFrame:
        data = []
        counter = 0
        for i in range(TEST_DATASET_ROWS):
            if i % 2 == 0 and counter < 11:
                data.append(econ_plus_mech_clg_row())
                counter += 1  # only simulate 10 OS changes
            else:
                data.append(mech_clg_row())
        return pd.DataFrame(data)

    def test_fault(self):
        fault_df = self.fault_df().set_index(generate_timestamp())
        results = fc4.apply(fault_df)
        actual = results["fc4_flag"].sum()
        expected = 1
        message = f"FC4 fault_df actual is {actual} and expected is {expected}"
        assert actual == expected, message


class TestNoFault(object):

    def no_fault_df(self) -> pd.DataFrame:
        data = []
        for i in range(TEST_DATASET_ROWS):
            data.append(mech_clg_row())
        return pd.DataFrame(data)

    def test_no_fault(self):
        no_fault_df = self.no_fault_df().set_index(generate_timestamp())
        results = fc4.apply(no_fault_df)
        actual = results["fc4_flag"].sum()
        expected = 0
        message = f"FC4 no_fault_df actual is {actual} and expected is {expected}"
        assert actual == expected, message


class TestFaultOnInt(object):

    def fault_df_on_output_int(self) -> pd.DataFrame:
        data = []
        for i in range(TEST_DATASET_ROWS):
            if i % 2 == 0:
                data.append(econ_plus_mech_clg_row_int())
            else:
                data.append(mech_clg_row())
        return pd.DataFrame(data)

    def test_fault_on_int(self):
        fault_df_on_output_int = self.fault_df_on_output_int().set_index(
            generate_timestamp()
        )
        with pytest.raises(
            TypeError,
            match=HelperUtils().float_int_check_err(TEST_SUPPLY_VFD_SPEED_COL),
        ):
            fc4.apply(fault_df_on_output_int)


class TestFaultOnFloatGreaterThanOne(object):

    def fault_df_on_output_greater_than_one(self) -> pd.DataFrame:
        data = []
        for i in range(TEST_DATASET_ROWS):
            if i % 2 == 0:
                data.append(econ_plus_mech_clg_row_float_greater_than_one())
            else:
                data.append(mech_clg_row())
        return pd.DataFrame(data)

    def test_fault_on_float_greater_than_one(self):
        fault_df_on_output_greater_than_one = (
            self.fault_df_on_output_greater_than_one().set_index(generate_timestamp())
        )
        with pytest.raises(
            TypeError,
            match=HelperUtils().float_max_check_err(TEST_SUPPLY_VFD_SPEED_COL),
        ):
            fc4.apply(fault_df_on_output_greater_than_one)


class TestFaultOnMixedTypes(object):

    def fault_df_on_mixed_types(self) -> pd.DataFrame:
        data = []
        for i in range(TEST_DATASET_ROWS):
            if i % 2 == 0:
                data.append(
                    {
                        TEST_MIX_AIR_DAMPER_COL: 0.6,
                        TEST_HEATING_COIL_SIG_COL: 0.0,
                        TEST_COOLING_COIL_SIG_COL: 0.6,
                        TEST_SUPPLY_VFD_SPEED_COL: 1.1,
                    }
                )
            else:
                data.append(mech_clg_row())
        return pd.DataFrame(data)

    def test_fault_on_mixed_types(self):
        fault_df_on_mixed_types = self.fault_df_on_mixed_types().set_index(
            generate_timestamp()
        )
        with pytest.raises(
            TypeError,
            match=HelperUtils().float_max_check_err(TEST_SUPPLY_VFD_SPEED_COL),
        ):
            fc4.apply(fault_df_on_mixed_types)
