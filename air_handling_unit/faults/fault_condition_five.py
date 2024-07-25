import pandas as pd
import pandas.api.types as pdtypes
from air_handling_unit.faults.fault_condition import FaultCondition
from air_handling_unit.faults.helper_utils import HelperUtils

class FaultConditionFive(FaultCondition):
    """ Class provides the definitions for Fault Condition 5.
        SAT too low; should be higher than MAT in HTG MODE
        --Broken heating valve or other mechanical issue
        related to heat valve not working as designed
    """

    def __init__(self, dict_):
        self.mix_degf_err_thres = float
        self.supply_degf_err_thres = float
        self.delta_t_supply_fan = float
        self.mat_col = str
        self.sat_col = str
        self.heating_sig_col = str
        self.supply_vfd_speed_col = str
        self.troubleshoot_mode = bool  # default to False
        self.rolling_window_size = int

        self.set_attributes(dict_)

    # fault only active if fan is running and htg vlv is modulating
    # OS 1 is heating mode only fault
    def apply(self, df: pd.DataFrame) -> pd.DataFrame:
        if self.troubleshoot_mode:
            self.troubleshoot_cols(df)

        # check analog outputs [data with units of %] are floats only            
        columns_to_check = [self.supply_vfd_speed_col, self.heating_sig_col]

        for col in columns_to_check:
            self.check_analog_pct(df, [col])

        df["sat_check"] = df[self.sat_col] + self.supply_degf_err_thres
        df["mat_check"] = (
                df[self.mat_col] - self.mix_degf_err_thres + self.delta_t_supply_fan
        )

        df["combined_check"] = (
                (df["sat_check"] <= df["mat_check"])
                # this is to make fault only active in OS1 for htg mode only
                # and fan is running. Some control programming may use htg
                # vlv when AHU is off to prevent low limit freeze alarms
                & (df[self.heating_sig_col] > 0.01)
                & (df[self.supply_vfd_speed_col] > 0.01)
        )

        # Rolling sum to count consecutive trues
        rolling_sum = df["combined_check"].rolling(window=self.rolling_window_size).sum()
        # Set flag to 1 if rolling sum equals the window size
        df["fc5_flag"] = (rolling_sum == self.rolling_window_size).astype(int)

        if self.troubleshoot_mode:
            print("Troubleshoot mode enabled - not removing helper columns")
            del df["mat_check"]
            del df["sat_check"]
            del df["combined_check"]

        return df
