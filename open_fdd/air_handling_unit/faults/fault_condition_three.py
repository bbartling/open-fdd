import pandas as pd
import numpy as np
from open_fdd.air_handling_unit.faults.fault_condition import (
    FaultCondition,
    MissingColumnError,
)
import sys


class FaultConditionThree(FaultCondition):
    """Class provides the definitions for Fault Condition 3.
    Mix temperature too high; should be between outside and return air.
    """

    def __init__(self, dict_):
        super().__init__()
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

        # Set required columns specific to this fault condition
        self.required_columns = [
            self.mat_col,
            self.rat_col,
            self.oat_col,
            self.supply_vfd_speed_col,
        ]

    def get_required_columns(self) -> str:
        """Returns a string representation of the required columns."""
        return f"Required columns for FaultConditionThree: {', '.join(self.required_columns)}"

    def apply(self, df: pd.DataFrame) -> pd.DataFrame:
        try:
            # Ensure all required columns are present
            self.check_required_columns(df)

            if self.troubleshoot_mode:
                self.troubleshoot_cols(df)

            # Check analog outputs [data with units of %] are floats only
            columns_to_check = [self.supply_vfd_speed_col]
            self.check_analog_pct(df, columns_to_check)

            # Fault condition-specific checks / flags
            df["mat_check"] = df[self.mat_col] - self.mix_degf_err_thres
            df["temp_min_check"] = np.maximum(
                df[self.rat_col] + self.return_degf_err_thres,
                df[self.oat_col] + self.outdoor_degf_err_thres,
            )

            df["combined_check"] = (df["mat_check"] > df["temp_min_check"]) & (
                df[self.supply_vfd_speed_col] > 0.01
            )

            # Rolling sum to count consecutive trues
            rolling_sum = (
                df["combined_check"].rolling(window=self.rolling_window_size).sum()
            )
            # Set flag to 1 if rolling sum equals the window size
            df["fc3_flag"] = (rolling_sum >= self.rolling_window_size).astype(int)

            if self.troubleshoot_mode:
                print("Troubleshoot mode enabled - not removing helper columns")
                sys.stdout.flush()
                del df["mat_check"]
                del df["temp_min_check"]
                del df["combined_check"]

            return df

        except MissingColumnError as e:
            print(f"Error: {e.message}")
            sys.stdout.flush()
            raise e  # Re-raise the exception so it can be caught by pytest
