import pandas as pd
import numpy as np
from open_fdd.air_handling_unit.faults.fault_condition import FaultCondition
from open_fdd.air_handling_unit.faults.helper_utils import HelperUtils
import sys


class FaultConditionSeven(FaultCondition):
    """Class provides the definitions for Fault Condition 7.
    Very similar to FC 13 but uses heating valve.
    Supply air temperature too low in full heating.
    """

    def __init__(self, dict_):
        self.supply_degf_err_thres = float
        self.sat_col = str
        self.sat_setpoint_col = str
        self.heating_sig_col = str
        self.supply_vfd_speed_col = str
        self.troubleshoot_mode = bool  # default to False
        self.rolling_window_size = int

        self.set_attributes(dict_)

    def apply(self, df: pd.DataFrame) -> pd.DataFrame:
        if self.troubleshoot_mode:
            self.troubleshoot_cols(df)

        # Check analog outputs [data with units of %] are floats only
        columns_to_check = [self.supply_vfd_speed_col, self.heating_sig_col]
        self.check_analog_pct(df, columns_to_check)

        # Fault condition-specific checks / flags
        df["sat_check"] = df[self.sat_setpoint_col] - self.supply_degf_err_thres

        df["combined_check"] = (
            (df[self.sat_col] < df["sat_check"])
            & (df[self.heating_sig_col] > 0.9)
            & (df[self.supply_vfd_speed_col] > 0)
        )

        # Rolling sum to count consecutive trues
        rolling_sum = (
            df["combined_check"].rolling(window=self.rolling_window_size).sum()
        )
        # Set flag to 1 if rolling sum equals the window size
        df["fc7_flag"] = (rolling_sum >= self.rolling_window_size).astype(int)

        if self.troubleshoot_mode:
            print("Troubleshoot mode enabled - not removing helper columns")
            sys.stdout.flush()
            del df["sat_check"]
            del df["combined_check"]

        return df
