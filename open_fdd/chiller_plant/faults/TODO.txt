# import pandas as pd
# from open_fdd.central_plant.faults.fault_condition import FaultCondition
# import sys


class FaultConditionLowDeltaT(FaultCondition):
    """Class provides the definitions for Low Delta T Fault Condition in Chiller Plant.

    This fault condition flags situations where the delta T (difference between supply
    and return temperatures) is below a certain threshold, indicating reduced chiller
    efficiency and potential performance issues.
    """

    def __init__(self, dict_):
        self.low_delta_t_threshold = float
        self.chw_supply_temp_col = str
        self.chw_return_temp_col = str
        self.chw_flow_rate_col = str
        self.rolling_window_size = int
        self.troubleshoot_mode = bool  # default to False

        self.set_attributes(dict_)

    def apply(self, df: pd.DataFrame) -> pd.DataFrame:
        if self.troubleshoot_mode:
            self.troubleshoot_cols(df)

        # Calculate the delta T
        df["delta_t"] = df[self.chw_return_temp_col] - df[self.chw_supply_temp_col]

        # Check if delta T is below the threshold
        df["low_delta_t_check"] = df["delta_t"] < self.low_delta_t_threshold

        # Rolling sum to count consecutive trues
        rolling_sum = (
            df["low_delta_t_check"].rolling(window=self.rolling_window_size).sum()
        )

        # Set flag to 1 if rolling sum equals the window size
        df["low_delta_t_flag"] = (rolling_sum >= self.rolling_window_size).astype(int)

        if self.troubleshoot_mode:
            print("Troubleshoot mode enabled - not removing helper columns")
            sys.stdout.flush()
            del df["delta_t"]
            del df["low_delta_t_check"]

        return df
