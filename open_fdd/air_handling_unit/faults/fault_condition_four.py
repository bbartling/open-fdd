import pandas as pd
from open_fdd.air_handling_unit.faults.fault_condition import (
    FaultCondition,
    MissingColumnError,
)
import sys


class FaultConditionFour(FaultCondition):
    """Class provides the definitions for Fault Condition 4.

    This fault flags excessive operating states on the AHU
    if its hunting between heating, econ, econ+mech, and
    a mech clg modes. The code counts how many operating
    changes in an hour and will throw a fault if there is
    excessive OS changes to flag control sys hunting.
    """

    def __init__(self, dict_):
        super().__init__()
        self.delta_os_max = float
        self.ahu_min_oa_dpr = float
        self.economizer_sig_col = str
        self.heating_sig_col = str
        self.cooling_sig_col = str
        self.supply_vfd_speed_col = str
        self.troubleshoot_mode = bool  # default to False

        self.set_attributes(dict_)

        # Set required columns specific to this fault condition
        self.required_columns = [
            self.economizer_sig_col,
            self.heating_sig_col,
            self.cooling_sig_col,
            self.supply_vfd_speed_col,
        ]

    def get_required_columns(self) -> str:
        """Returns a string representation of the required columns."""
        return f"Required columns for FaultConditionFour: {', '.join(self.required_columns)}"

    def apply(self, df: pd.DataFrame) -> pd.DataFrame:
        try:
            # Ensure all required columns are present
            self.check_required_columns(df)

            if self.troubleshoot_mode:
                self.troubleshoot_cols(df)

            # Check analog outputs [data with units of %] are floats only
            columns_to_check = [
                self.economizer_sig_col,
                self.heating_sig_col,
                self.cooling_sig_col,
                self.supply_vfd_speed_col,
            ]

            for col in columns_to_check:
                self.check_analog_pct(df, [col])

            print("=" * 50)
            print("Warning: The program is in FC4 and resampling the data")
            print("to compute AHU OS state changes per hour")
            print("to flag any hunting issue")
            print("and this usually takes a while to run...")
            print("=" * 50)

            sys.stdout.flush()

            # AHU htg only mode based on OA damper @ min oa and only htg pid/vlv modulating
            df["heating_mode"] = (
                (df[self.heating_sig_col] > 0)
                & (df[self.cooling_sig_col] == 0)
                & (df[self.supply_vfd_speed_col] > 0)
                & (df[self.economizer_sig_col] == self.ahu_min_oa_dpr)
            )

            # AHU econ only mode based on OA damper modulating and clg htg = zero
            df["econ_only_cooling_mode"] = (
                (df[self.heating_sig_col] == 0)
                & (df[self.cooling_sig_col] == 0)
                & (df[self.supply_vfd_speed_col] > 0)
                & (df[self.economizer_sig_col] > self.ahu_min_oa_dpr)
            )

            # AHU econ+mech clg mode based on OA damper modulating for cooling and clg pid/vlv modulating
            df["econ_plus_mech_cooling_mode"] = (
                (df[self.heating_sig_col] == 0)
                & (df[self.cooling_sig_col] > 0)
                & (df[self.supply_vfd_speed_col] > 0)
                & (df[self.economizer_sig_col] > self.ahu_min_oa_dpr)
            )

            # AHU mech mode based on OA damper @ min OA and clg pid/vlv modulating
            df["mech_cooling_only_mode"] = (
                (df[self.heating_sig_col] == 0)
                & (df[self.cooling_sig_col] > 0)
                & (df[self.supply_vfd_speed_col] > 0)
                & (df[self.economizer_sig_col] == self.ahu_min_oa_dpr)
            )

            # Fill non-finite values with zero or drop them
            df = df.fillna(0)

            df = df.astype(int)
            df = df.resample("60min").apply(lambda x: (x.eq(1) & x.shift().ne(1)).sum())

            df["fc4_flag"] = (
                df[df.columns].gt(self.delta_os_max).any(axis=1).astype(int)
            )

            return df

        except MissingColumnError as e:
            print(f"Error: {e.message}")
            sys.stdout.flush()
            raise e  # Re-raise the exception so it can be caught by pytest
