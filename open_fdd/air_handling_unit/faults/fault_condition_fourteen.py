import pandas as pd
import numpy as np
import operator
from open_fdd.air_handling_unit.faults.fault_condition import (
    FaultCondition,
    MissingColumnError,
)
import sys


class FaultConditionFourteen(FaultCondition):
    """Class provides the definitions for Fault Condition 14.
    Temperature drop across inactive cooling coil.
    Requires coil leaving temp sensor.
    """

    def __init__(self, dict_):
        super().__init__()
        self.delta_t_supply_fan = float
        self.coil_temp_enter_err_thres = float
        self.coil_temp_leav_err_thres = float
        self.clg_coil_enter_temp_col = str
        self.clg_coil_leave_temp_col = str
        self.ahu_min_oa_dpr = float
        self.cooling_sig_col = str
        self.heating_sig_col = str
        self.economizer_sig_col = str
        self.supply_vfd_speed_col = str
        self.troubleshoot_mode = bool  # default to False
        self.rolling_window_size = int

        self.set_attributes(dict_)

        # Set required columns specific to this fault condition
        self.required_columns = [
            self.clg_coil_enter_temp_col,
            self.clg_coil_leave_temp_col,
            self.cooling_sig_col,
            self.heating_sig_col,
            self.economizer_sig_col,
            self.supply_vfd_speed_col,
        ]

    def get_required_columns(self) -> str:
        """Returns a string representation of the required columns."""
        return f"Required columns for FaultConditionFourteen: {', '.join(self.required_columns)}"

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
                self.heating_sig_col,
                self.supply_vfd_speed_col,
            ]
            self.check_analog_pct(df, columns_to_check)

            # Create helper columns
            df["clg_delta_temp"] = (
                df[self.clg_coil_enter_temp_col] - df[self.clg_coil_leave_temp_col]
            )

            df["clg_delta_sqrted"] = (
                np.sqrt(
                    self.coil_temp_enter_err_thres**2 + self.coil_temp_leav_err_thres**2
                )
                + self.delta_t_supply_fan
            )

            df["combined_check"] = operator.or_(
                (df["clg_delta_temp"] >= df["clg_delta_sqrted"])
                # verify AHU is in OS2 only free cooling mode
                & (df[self.economizer_sig_col] > self.ahu_min_oa_dpr)
                & (df[self.cooling_sig_col] < 0.1),  # OR
                (df["clg_delta_temp"] >= df["clg_delta_sqrted"])
                # verify AHU is running in OS 1 at near full heat
                & (df[self.heating_sig_col] > 0.0)
                & (df[self.supply_vfd_speed_col] > 0.0),
            )

            # Rolling sum to count consecutive trues
            rolling_sum = (
                df["combined_check"].rolling(window=self.rolling_window_size).sum()
            )
            # Set flag to 1 if rolling sum equals the window size
            df["fc14_flag"] = (rolling_sum >= self.rolling_window_size).astype(int)

            if self.troubleshoot_mode:
                print("Troubleshoot mode enabled - not removing helper columns")
                sys.stdout.flush()
                del df["clg_delta_temp"]
                del df["clg_delta_sqrted"]
                del df["combined_check"]

            return df

        except MissingColumnError as e:
            print(f"Error: {e.message}")
            sys.stdout.flush()
            raise e  # Re-raise the exception so it can be caught by pytest
