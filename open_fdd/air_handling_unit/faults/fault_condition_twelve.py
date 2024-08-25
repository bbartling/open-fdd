import pandas as pd
import numpy as np
import operator
from open_fdd.air_handling_unit.faults.fault_condition import (
    FaultCondition,
    MissingColumnError,
)
import sys


class FaultConditionTwelve(FaultCondition):
    """Class provides the definitions for Fault Condition 12.
    Supply air temperature too high; should be less than
    mix air temperature in economizer plus mech cooling mode.
    """

    def __init__(self, dict_):
        super().__init__()
        self.delta_t_supply_fan = float
        self.mix_degf_err_thres = float
        self.supply_degf_err_thres = float
        self.ahu_min_oa_dpr = float
        self.sat_col = str
        self.mat_col = str
        self.cooling_sig_col = str
        self.economizer_sig_col = str
        self.troubleshoot_mode = bool  # default False
        self.rolling_window_size = int

        self.equation_string = (
            "fc12_flag = 1 if SAT >= MAT + εMAT in "
            "economizer + mech cooling mode for N consecutive values else 0 \n"
        )
        self.description_string = (
            "Fault Condition 12: Supply air temperature too high; should be less than "
            "mixed air temperature in economizer plus mechanical cooling mode \n"
        )
        self.required_column_description = (
            "Required inputs are the supply air temperature, mixed air temperature, "
            "cooling signal, and economizer signal \n"
        )
        self.error_string = f"One or more required columns are missing or None \n"

        self.set_attributes(dict_)

        # Set required columns specific to this fault condition
        self.required_columns = [
            self.sat_col,
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

            # Create helper columns
            df["sat_minus_saterr_delta_supply_fan"] = (
                df[self.sat_col] - self.supply_degf_err_thres - self.delta_t_supply_fan
            )
            df["mat_plus_materr"] = df[self.mat_col] + self.mix_degf_err_thres

            df["combined_check"] = operator.or_(
                # OS4 AHU state clg @ min OA
                (df["sat_minus_saterr_delta_supply_fan"] > df["mat_plus_materr"])
                # verify AHU in OS4 mode
                & (df[self.cooling_sig_col] > 0.01)
                & (df[self.economizer_sig_col] == self.ahu_min_oa_dpr),  # OR
                (df["sat_minus_saterr_delta_supply_fan"] > df["mat_plus_materr"])
                # verify AHU is running in OS 3 clg mode in 100 OA
                & (df[self.cooling_sig_col] > 0.01)
                & (df[self.economizer_sig_col] > 0.9),
            )

            # Rolling sum to count consecutive trues
            rolling_sum = (
                df["combined_check"].rolling(window=self.rolling_window_size).sum()
            )
            # Set flag to 1 if rolling sum equals the window size
            df["fc12_flag"] = (rolling_sum >= self.rolling_window_size).astype(int)

            if self.troubleshoot_mode:
                print("Troubleshoot mode enabled - not removing helper columns")
                sys.stdout.flush()
                del df["sat_minus_saterr_delta_supply_fan"]
                del df["mat_plus_materr"]
                del df["combined_check"]

            return df

        except MissingColumnError as e:
            print(f"Error: {e.message}")
            sys.stdout.flush()
            raise e
