import pandas as pd
import numpy as np
from open_fdd.air_handling_unit.faults.fault_condition import FaultCondition
from open_fdd.air_handling_unit.faults.helper_utils import HelperUtils
import sys

class FaultConditionEight(FaultCondition):
    """ Class provides the definitions for Fault Condition 8.
        Supply air temperature and mix air temperature should 
        be approx equal in economizer mode.
    """

    def __init__(self, dict_):
        self.delta_t_supply_fan = float
        self.mix_degf_err_thres = float
        self.supply_degf_err_thres = float
        self.ahu_min_oa_dpr = float
        self.mat_col = str
        self.sat_col = str
        self.economizer_sig_col = str
        self.cooling_sig_col = str
        self.troubleshoot_mode = bool  # default should be False
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

        df["sat_fan_mat"] = abs(df[self.sat_col] - self.delta_t_supply_fan - df[self.mat_col])
        df["sat_mat_sqrted"] = np.sqrt(self.supply_degf_err_thres ** 2 + self.mix_degf_err_thres ** 2)

        df["combined_check"] = (
            (df["sat_fan_mat"] > df["sat_mat_sqrted"])
            & (df[self.economizer_sig_col] > self.ahu_min_oa_dpr)
            & (df[self.cooling_sig_col] < 0.1)
        )

        # Rolling sum to count consecutive trues
        rolling_sum = df["combined_check"].rolling(window=self.rolling_window_size).sum()
        # Set flag to 1 if rolling sum equals the window size
        df["fc8_flag"] = (rolling_sum >= self.rolling_window_size).astype(int)

        if self.troubleshoot_mode:
            print("Troubleshoot mode enabled - not removing helper columns")
            sys.stdout.flush()
            del df["sat_fan_mat"]
            del df["sat_mat_sqrted"]
            del df["combined_check"]

        return df
