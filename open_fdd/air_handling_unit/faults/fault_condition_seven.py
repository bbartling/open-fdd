import pandas as pd
from open_fdd.air_handling_unit.faults.fault_condition import (
    FaultCondition,
    MissingColumnError,
)
import sys


class FaultConditionSeven(FaultCondition):
    """Class provides the definitions for Fault Condition 7.
    Very similar to FC 13 but uses heating valve.
    Supply air temperature too low in full heating.
    """

    def __init__(self, dict_):
        super().__init__()
        self.supply_degf_err_thres = float
        self.sat_col = str
        self.sat_setpoint_col = str
        self.heating_sig_col = str
        self.supply_vfd_speed_col = str
        self.troubleshoot_mode = bool  # default to False
        self.rolling_window_size = int

        self.equation_string = (
            "fc7_flag = 1 if SAT < (SATSP - εSAT) in full heating mode "
            "and VFD speed > 0 for N consecutive values else 0 \n"
        )
        self.description_string = (
            "Fault Condition 7: Supply air temperature too low in full heating mode "
            "with heating valve fully open \n"
        )
        self.required_column_description = (
            "Required inputs are the supply air temperature, supply air temperature setpoint, "
            "heating signal, and supply fan VFD speed \n"
        )
        self.error_string = f"One or more required columns are missing or None \n"

        self.set_attributes(dict_)

        # Set required columns specific to this fault condition
        self.required_columns = [
            self.sat_col,
            self.sat_setpoint_col,
            self.heating_sig_col,
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
            columns_to_check = [self.supply_vfd_speed_col, self.heating_sig_col]
            self.check_analog_pct(df, columns_to_check)

            # Fault condition-specific checks / flags
            df["sat_check"] = df[self.sat_setpoint_col] - self.supply_degf_err_thres

            df["combined_check"] = (
                (df[self.sat_col] < df["sat_check"])
                & (df[self.heating_sig_col] > 0.9)
                & (df[self.supply_vfd_speed_col] > 0)
            )

            # Rolling sum to count consecutive trues
            rolling_sum = (
                df["combined_check"].rolling(window=self.rolling_window_size).sum()
            )
            # Set flag to 1 if rolling sum equals the window size
            df["fc7_flag"] = (rolling_sum >= self.rolling_window_size).astype(int)

            if self.troubleshoot_mode:
                print("Troubleshoot mode enabled - not removing helper columns")
                sys.stdout.flush()
                del df["sat_check"]
                del df["combined_check"]

            return df

        except MissingColumnError as e:
            print(f"Error: {e.message}")
            sys.stdout.flush()
            raise e
