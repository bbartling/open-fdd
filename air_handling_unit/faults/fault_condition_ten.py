import pandas as pd
import numpy as np
from air_handling_unit.faults.fault_condition import FaultCondition
from air_handling_unit.faults.helper_utils import HelperUtils

class FaultConditionTen(FaultCondition):
    """ Class provides the definitions for Fault Condition 10.
        Outdoor air temperature and mix air temperature should 
        be approx equal in economizer plus mech cooling mode.
    """

    def __init__(self, dict_):
        self.outdoor_degf_err_thres = float
        self.mix_degf_err_thres = float
        self.oat_col = str
        self.mat_col = str
        self.cooling_sig_col = str
        self.economizer_sig_col = str
        self.troubleshoot_mode = bool  # default False,
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

        df["abs_mat_minus_oat"] = abs(df[self.mat_col] - df[self.oat_col])
        df["mat_oat_sqrted"] = np.sqrt(
            self.mix_degf_err_thres ** 2 + self.outdoor_degf_err_thres ** 2
        )

        df["combined_check"] = (
            (df["abs_mat_minus_oat"] > df["mat_oat_sqrted"])
            # verify ahu is running in OS 3 clg mode in min OA
            & (df[self.cooling_sig_col] > 0.01)
            & (df[self.economizer_sig_col] > 0.9)
        )

        # Rolling sum to count consecutive trues
        rolling_sum = df["combined_check"].rolling(window=self.rolling_window_size).sum()
        # Set flag to 1 if rolling sum equals the window size
        df["fc10_flag"] = (rolling_sum >= self.rolling_window_size).astype(int)

        if self.troubleshoot_mode:
            print("Troubleshoot mode enabled - not removing helper columns")
            del df["abs_mat_minus_oat"]
            del df["mat_oat_sqrted"]
            del df["combined_check"]

        return df
