import pandas as pd
import operator
from open_fdd.air_handling_unit.faults.fault_condition import (
    FaultCondition,
    MissingColumnError,
)
import sys


class FaultConditionThirteen(FaultCondition):
    """Class provides the definitions for Fault Condition 13.
    Supply air temperature too high in full cooling
    in economizer plus mech cooling mode
    """

    def __init__(self, dict_):
        super().__init__()
        self.supply_degf_err_thres = float
        self.ahu_min_oa_dpr = float
        self.sat_col = str
        self.sat_setpoint_col = str
        self.cooling_sig_col = str
        self.economizer_sig_col = str
        self.troubleshoot_mode = bool  # default False
        self.rolling_window_size = int

        self.equation_string = (
            "fc13_flag = 1 if SAT > (SATSP + εSAT) in "
            "economizer + mech cooling mode for N consecutive values else 0 \n"
        )
        self.description_string = (
            "Fault Condition 13: Supply air temperature too high in full cooling "
            "in economizer plus mechanical cooling mode \n"
        )
        self.required_column_description = (
            "Required inputs are the supply air temperature, supply air temperature setpoint, "
            "cooling signal, and economizer signal \n"
        )
        self.error_string = f"One or more required columns are missing or None \n"

        self.set_attributes(dict_)

        # Set required columns specific to this fault condition
        self.required_columns = [
            self.sat_col,
            self.sat_setpoint_col,
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
            df["sat_greater_than_sp_calc"] = (
                df[self.sat_col]
                > df[self.sat_setpoint_col] + self.supply_degf_err_thres
            )

            df["combined_check"] = operator.or_(
                ((df["sat_greater_than_sp_calc"]))
                # OS4 AHU state clg @ min OA
                & (df[self.cooling_sig_col] > 0.01)
                & (df[self.economizer_sig_col] == self.ahu_min_oa_dpr),  # OR
                ((df["sat_greater_than_sp_calc"]))
                # verify ahu is running in OS 3 clg mode in 100 OA
                & (df[self.cooling_sig_col] > 0.01)
                & (df[self.economizer_sig_col] > 0.9),
            )

            # Rolling sum to count consecutive trues
            rolling_sum = (
                df["combined_check"].rolling(window=self.rolling_window_size).sum()
            )
            # Set flag to 1 if rolling sum equals the window size
            df["fc13_flag"] = (rolling_sum >= self.rolling_window_size).astype(int)

            if self.troubleshoot_mode:
                print("Troubleshoot mode enabled - not removing helper columns")
                sys.stdout.flush()
                del df["sat_greater_than_sp_calc"]
                del df["combined_check"]

            return df

        except MissingColumnError as e:
            print(f"Error: {e.message}")
            sys.stdout.flush()
            raise e
