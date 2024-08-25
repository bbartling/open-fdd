import pandas as pd
import numpy as np
from open_fdd.air_handling_unit.faults.fault_condition import (
    FaultCondition,
    MissingColumnError,
)
import sys


class FaultConditionTen(FaultCondition):
    """Class provides the definitions for Fault Condition 10.
    Outdoor air temperature and mix air temperature should
    be approx equal in economizer plus mech cooling mode.
    """

    def __init__(self, dict_):
        super().__init__()
        self.outdoor_degf_err_thres = float
        self.mix_degf_err_thres = float
        self.oat_col = str
        self.mat_col = str
        self.cooling_sig_col = str
        self.economizer_sig_col = str
        self.troubleshoot_mode = bool  # default False,
        self.rolling_window_size = int

        self.equation_string = (
            "fc10_flag = 1 if |OAT - MAT| > √(εOAT² + εMAT²) in "
            "economizer + mech cooling mode for N consecutive values else 0 \n"
        )
        self.description_string = (
            "Fault Condition 10: Outdoor air temperature and mixed air temperature "
            "should be approximately equal in economizer plus mechanical cooling mode \n"
        )
        self.required_column_description = (
            "Required inputs are the outside air temperature, mixed air temperature, "
            "cooling signal, and economizer signal \n"
        )
        self.error_string = f"One or more required columns are missing or None \n"

        self.set_attributes(dict_)

        # Set required columns specific to this fault condition
        self.required_columns = [
            self.oat_col,
            self.mat_col,
            self.cooling_sig_col,
            self.economizer_sig_col,
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
            columns_to_check = [
                self.economizer_sig_col,
                self.cooling_sig_col,
            ]
            self.check_analog_pct(df, columns_to_check)

            df["abs_mat_minus_oat"] = abs(df[self.mat_col] - df[self.oat_col])
            df["mat_oat_sqrted"] = np.sqrt(
                self.mix_degf_err_thres**2 + self.outdoor_degf_err_thres**2
            )

            df["combined_check"] = (
                (df["abs_mat_minus_oat"] > df["mat_oat_sqrted"])
                # verify AHU is running in OS 3 clg mode in min OA
                & (df[self.cooling_sig_col] > 0.01)
                & (df[self.economizer_sig_col] > 0.9)
            )

            # Rolling sum to count consecutive trues
            rolling_sum = (
                df["combined_check"].rolling(window=self.rolling_window_size).sum()
            )
            # Set flag to 1 if rolling sum equals the window size
            df["fc10_flag"] = (rolling_sum >= self.rolling_window_size).astype(int)

            if self.troubleshoot_mode:
                print("Troubleshoot mode enabled - not removing helper columns")
                sys.stdout.flush()
                del df["abs_mat_minus_oat"]
                del df["mat_oat_sqrted"]
                del df["combined_check"]

            return df

        except MissingColumnError as e:
            print(f"Error: {e.message}")
            sys.stdout.flush()
            raise e
