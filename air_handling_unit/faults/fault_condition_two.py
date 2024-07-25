import pandas as pd
import numpy as np
from air_handling_unit.faults.fault_condition import FaultCondition

class FaultConditionTwo(FaultCondition):
    """ Class provides the definitions for Fault Condition 2.
        Mix temperature too low; should be between outside and return air.
    """

    def __init__(self, dict_):
        """
        :param dict_:
        """
        self.mix_degf_err_thres = float
        self.return_degf_err_thres = float
        self.outdoor_degf_err_thres = float
        self.mat_col = str
        self.rat_col = str
        self.oat_col = str
        self.supply_vfd_speed_col = str
        self.troubleshoot_mode = bool  # default to False
        self.rolling_window_size = int

        self.set_attributes(dict_)

    def apply(self, df: pd.DataFrame) -> pd.DataFrame:
        if self.troubleshoot_mode:
            self.troubleshoot_cols(df)

        # Check analog outputs [data with units of %] are floats only
        columns_to_check = [self.supply_vfd_speed_col]
        self.check_analog_pct(df, columns_to_check)

        # Fault condition-specific checks / flags
        df["mat_check"] = df[self.mat_col] + self.mix_degf_err_thres
        df["temp_min_check"] = np.minimum(
            df[self.rat_col] - self.return_degf_err_thres,
            df[self.oat_col] - self.outdoor_degf_err_thres,
        )

        df["combined_check"] = (
            (df["mat_check"] < df["temp_min_check"])
            & (df[self.supply_vfd_speed_col] > 0.01)
        )

        # Rolling sum to count consecutive trues
        rolling_sum = df["combined_check"].rolling(window=self.rolling_window_size).sum()
        # Set flag to 1 if rolling sum equals the window size
        df["fc2_flag"] = (rolling_sum >= self.rolling_window_size).astype(int)

        if self.troubleshoot_mode:
            print("Troubleshoot mode enabled - not removing helper columns")
            del df["mat_check"]
            del df["temp_min_check"]
            del df["combined_check"]

        return df
