import pandas as pd
import numpy as np
from open_fdd.air_handling_unit.faults.fault_condition import (
    FaultCondition,
    MissingColumnError,
)
import sys


class FaultConditionEight(FaultCondition):
    """Class provides the definitions for Fault Condition 8.
    Supply air temperature and mix air temperature should
    be approx equal in economizer mode.
    """

    def __init__(self, dict_):
        super().__init__()
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

        self.equation_string = (
            "fc8_flag = 1 if |SAT - MAT - ΔT_fan| > √(εSAT² + εMAT²) "
            "in economizer mode for N consecutive values else 0 \n"
        )
        self.description_string = (
            "Fault Condition 8: Supply air temperature and mixed air temperature should "
            "be approximately equal in economizer mode \n"
        )
        self.required_column_description = (
            "Required inputs are the mixed air temperature, supply air temperature, "
            "economizer signal, and cooling signal \n"
        )
        self.error_string = f"One or more required columns are missing or None \n"

        self.set_attributes(dict_)

        # Set required columns specific to this fault condition
        self.required_columns = [
            self.mat_col,
            self.sat_col,
            self.economizer_sig_col,
            self.cooling_sig_col,
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

            df["sat_fan_mat"] = abs(
                df[self.sat_col] - self.delta_t_supply_fan - df[self.mat_col]
            )
            df["sat_mat_sqrted"] = np.sqrt(
                self.supply_degf_err_thres**2 + self.mix_degf_err_thres**2
            )

            df["combined_check"] = (
                (df["sat_fan_mat"] > df["sat_mat_sqrted"])
                & (df[self.economizer_sig_col] > self.ahu_min_oa_dpr)
                & (df[self.cooling_sig_col] < 0.1)
            )

            # Rolling sum to count consecutive trues
            rolling_sum = (
                df["combined_check"].rolling(window=self.rolling_window_size).sum()
            )
            # Set flag to 1 if rolling sum equals the window size
            df["fc8_flag"] = (rolling_sum >= self.rolling_window_size).astype(int)

            if self.troubleshoot_mode:
                print("Troubleshoot mode enabled - not removing helper columns")
                sys.stdout.flush()
                del df["sat_fan_mat"]
                del df["sat_mat_sqrted"]
                del df["combined_check"]

            return df

        except MissingColumnError as e:
            print(f"Error: {e.message}")
            sys.stdout.flush()
            raise e
