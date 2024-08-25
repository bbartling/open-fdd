import pandas as pd
import numpy as np
from open_fdd.air_handling_unit.faults.fault_condition import (
    FaultCondition,
    MissingColumnError,
)
import sys


class FaultConditionTwo(FaultCondition):
    """Class provides the definitions for Fault Condition 2.
    Mix temperature too low; should be between outside and return air.
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

        self.equation_string = (
            "fc2_flag = 1 if (MAT + εMAT < min(RAT - εRAT, OAT - εOAT)) and (VFDSPD > 0) "
            "for N consecutive values else 0 \n"
        )
        self.description_string = "Fault Condition 2: Mix temperature too low; should be between outside and return air \n"
        self.required_column_description = "Required inputs are the mix air temperature, return air temperature, outside air temperature, and supply fan VFD speed \n"
        self.error_string = f"One or more required columns are missing or None \n"

        self.set_attributes(dict_)

        # Set required columns specific to this fault condition
        self.required_columns = [
            self.mat_col,
            self.rat_col,
            self.oat_col,
            self.supply_vfd_speed_col,
        ]

        # Check if any of the required columns are None
        if any(col is None for col in self.required_columns):
            raise MissingColumnError(
                f"{self.error_string}"
                f"{self.equation_string}"
                f"{self.description_string}"
                f"{self.required_column_description}"
                f"{self.required_columns}"
            )

        # Ensure all required columns are strings
        self.required_columns = [str(col) for col in self.required_columns]

        self.mapped_columns = (
            f"Your config dictionary is mapped as: {', '.join(self.required_columns)}"
        )

    def get_required_columns(self) -> str:
        """Returns a string representation of the required columns."""
        return (
            f"{self.equation_string}"
            f"{self.description_string}"
            f"{self.required_column_description}"
            f"{self.mapped_columns}"
        )

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
            df["mat_check"] = df[self.mat_col] + self.mix_degf_err_thres
            df["temp_min_check"] = np.minimum(
                df[self.rat_col] - self.return_degf_err_thres,
                df[self.oat_col] - self.outdoor_degf_err_thres,
            )

            df["combined_check"] = (df["mat_check"] < df["temp_min_check"]) & (
                df[self.supply_vfd_speed_col] > 0.01
            )

            # Rolling sum to count consecutive trues
            rolling_sum = (
                df["combined_check"].rolling(window=self.rolling_window_size).sum()
            )
            # Set flag to 1 if rolling sum equals the window size
            df["fc2_flag"] = (rolling_sum >= self.rolling_window_size).astype(int)

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
            raise e
