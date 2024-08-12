import pandas as pd
import numpy as np
import operator
from open_fdd.air_handling_unit.faults.fault_condition import FaultCondition
from open_fdd.air_handling_unit.faults.helper_utils import HelperUtils
import sys


class FaultConditionThirteen(FaultCondition):
    """Class provides the definitions for Fault Condition 13.
    Supply air temperature too high in full cooling
    in economizer plus mech cooling mode
    """

    def __init__(self, dict_):
        self.supply_degf_err_thres = float
        self.ahu_min_oa_dpr = float
        self.sat_col = str
        self.sat_setpoint_col = str
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

        # Create helper columns
        df["sat_greater_than_sp_calc"] = (
            df[self.sat_col] > df[self.sat_setpoint_col] + self.supply_degf_err_thres
        )

        df["combined_check"] = operator.or_(
            ((df["sat_greater_than_sp_calc"]))
            # OS4 AHU state clg @ min OA
            & (df[self.cooling_sig_col] > 0.01)
            & (df[self.economizer_sig_col] == self.ahu_min_oa_dpr),  # OR
            ((df["sat_greater_than_sp_calc"]))
            # verify ahu is running in OS 3 clg mode in 100 OA
            & (df[self.cooling_sig_col] > 0.01) & (df[self.economizer_sig_col] > 0.9),
        )

        # Rolling sum to count consecutive trues
        rolling_sum = (
            df["combined_check"].rolling(window=self.rolling_window_size).sum()
        )
        # Set flag to 1 if rolling sum equals the window size
        df["fc13_flag"] = (rolling_sum >= self.rolling_window_size).astype(int)

        if self.troubleshoot_mode:
            print("Troubleshoot mode enabled - not removing helper columns")
            sys.stdout.flush()
            del df["sat_greater_than_sp_calc"]
            del df["combined_check"]

        return df
