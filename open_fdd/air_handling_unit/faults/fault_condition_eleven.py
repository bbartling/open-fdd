import pandas as pd
import numpy as np
from open_fdd.air_handling_unit.faults.fault_condition import FaultCondition
from open_fdd.air_handling_unit.faults.helper_utils import HelperUtils
import sys

class FaultConditionEleven(FaultCondition):
    """ Class provides the definitions for Fault Condition 11.
        Outside air temperature too low for 100% outdoor 
        air cooling in economizer cooling mode.

        Economizer performance fault
    """

    def __init__(self, dict_):
        self.delta_t_supply_fan = float
        self.outdoor_degf_err_thres = float
        self.supply_degf_err_thres = float
        self.sat_setpoint_col = str
        self.oat_col = str
        self.cooling_sig_col = str
        self.economizer_sig_col = str
        self.troubleshoot_mode = bool  # default False
        self.rolling_window_size = int

        self.set_attributes(dict_)

    def apply(self, df: pd.DataFrame) -> pd.DataFrame:
        if self.troubleshoot_mode:
            self.troubleshoot_cols(df)

        # Check analog outputs [data with units of %] are floats only
        columns_to_check = [
            self.economizer_sig_col,
            self.cooling_sig_col,
        ]
        self.check_analog_pct(df, columns_to_check)

        df["oat_plus_oaterror"] = df[self.oat_col] + self.outdoor_degf_err_thres
        df["satsp_delta_saterr"] = (
            df[self.sat_setpoint_col] - self.delta_t_supply_fan - self.supply_degf_err_thres
        )

        df["combined_check"] = (
            (df["oat_plus_oaterror"] < df["satsp_delta_saterr"])
            # verify ahu is running in OS 3 clg mode in 100 OA
            & (df[self.cooling_sig_col] > 0.01)
            & (df[self.economizer_sig_col] > 0.9)
        )

        # Rolling sum to count consecutive trues
        rolling_sum = df["combined_check"].rolling(window=self.rolling_window_size).sum()
        # Set flag to 1 if rolling sum equals the window size
        df["fc11_flag"] = (rolling_sum >= self.rolling_window_size).astype(int)

        if self.troubleshoot_mode:
            print("Troubleshoot mode enabled - not removing helper columns")
            sys.stdout.flush()
            del df["oat_plus_oaterror"]
            del df["satsp_delta_saterr"]
            del df["combined_check"]

        return df
