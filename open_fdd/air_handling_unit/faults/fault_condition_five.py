import pandas as pd
import pandas.api.types as pdtypes
from open_fdd.air_handling_unit.faults.fault_condition import (
    FaultCondition,
    MissingColumnError,
)
import sys


class FaultConditionFive(FaultCondition):
    """Class provides the definitions for Fault Condition 5.
    SAT too low; should be higher than MAT in HTG MODE
    --Broken heating valve or other mechanical issue
    related to heat valve not working as designed
    """

    def __init__(self, dict_):
        super().__init__()
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

        # Set required columns specific to this fault condition
        self.required_columns = [
            self.mat_col,
            self.sat_col,
            self.heating_sig_col,
            self.supply_vfd_speed_col,
        ]

    def get_required_columns(self) -> str:
        """Returns a string representation of the required columns."""
        return f"Required columns for FaultConditionFive: {', '.join(self.required_columns)}"

    def apply(self, df: pd.DataFrame) -> pd.DataFrame:
        try:
            # Ensure all required columns are present
            self.check_required_columns(df)

            if self.troubleshoot_mode:
                self.troubleshoot_cols(df)

            # Check analog outputs [data with units of %] are floats only
            columns_to_check = [self.supply_vfd_speed_col, self.heating_sig_col]

            for col in columns_to_check:
                self.check_analog_pct(df, [col])

            df["sat_check"] = df[self.sat_col] + self.supply_degf_err_thres
            df["mat_check"] = (
                df[self.mat_col] - self.mix_degf_err_thres + self.delta_t_supply_fan
            )

            df["combined_check"] = (
                (df["sat_check"] <= df["mat_check"])
                & (df[self.heating_sig_col] > 0.01)
                & (df[self.supply_vfd_speed_col] > 0.01)
            )

            # Rolling sum to count consecutive trues
            rolling_sum = (
                df["combined_check"].rolling(window=self.rolling_window_size).sum()
            )
            # Set flag to 1 if rolling sum equals the window size
            df["fc5_flag"] = (rolling_sum == self.rolling_window_size).astype(int)

            if self.troubleshoot_mode:
                print("Troubleshoot mode enabled - not removing helper columns")
                sys.stdout.flush()
                del df["mat_check"]
                del df["sat_check"]
                del df["combined_check"]

            return df

        except MissingColumnError as e:
            print(f"Error: {e.message}")
            sys.stdout.flush()
            raise e  # Re-raise the exception so it can be caught by pytest
