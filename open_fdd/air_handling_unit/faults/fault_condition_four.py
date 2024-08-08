import pandas as pd
from open_fdd.air_handling_unit.faults.fault_condition import FaultCondition
from open_fdd.air_handling_unit.faults.helper_utils import HelperUtils
from open_fdd.air_handling_unit.faults.shared_utils import SharedUtils
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
        self.delta_os_max = float
        self.ahu_min_oa_dpr = float
        self.economizer_sig_col = str
        self.heating_sig_col = str
        self.cooling_sig_col = str
        self.supply_vfd_speed_col = str
        self.troubleshoot_mode = bool  # default to False

        self.set_attributes(dict_)

    def apply(self, df: pd.DataFrame) -> pd.DataFrame:
        if self.troubleshoot_mode:
            self.troubleshoot_cols(df)

        # Ensure columns are float type
        columns_to_check = [
            self.economizer_sig_col,
            self.heating_sig_col,
            self.cooling_sig_col,
            self.supply_vfd_speed_col,
        ]

        for col in columns_to_check:
            df = SharedUtils.convert_to_float(df, col)

        print("The program is in FC4 and resampling the data to compute AHU OS state changes per hour takes a while to run...")
        sys.stdout.flush()

        # Apply rolling average if needed
        df = SharedUtils.apply_rolling_average_if_needed(df)

        # AHU heating only mode based on OA damper @ min oa and only heating pid/vlv modulating
        df["heating_mode"] = (
            (df[self.heating_sig_col] > 0)
            & (df[self.cooling_sig_col] == 0)
            & (df[self.supply_vfd_speed_col] > 0)
            & (df[self.economizer_sig_col] == self.ahu_min_oa_dpr)
        )

        # AHU econ only mode based on OA damper modulating and cooling heating = zero
        df["econ_only_cooling_mode"] = (
            (df[self.heating_sig_col] == 0)
            & (df[self.cooling_sig_col] == 0)
            & (df[self.supply_vfd_speed_col] > 0)
            & (df[self.economizer_sig_col] > self.ahu_min_oa_dpr)
        )

        # AHU econ+mech cooling mode based on OA damper modulating for cooling and cooling pid/vlv modulating
        df["econ_plus_mech_cooling_mode"] = (
            (df[self.heating_sig_col] == 0)
            & (df[self.cooling_sig_col] > 0)
            & (df[self.supply_vfd_speed_col] > 0)
            & (df[self.economizer_sig_col] > self.ahu_min_oa_dpr)
        )

        # AHU mech mode based on OA damper @ min OA and cooling pid/vlv modulating
        df["mech_cooling_only_mode"] = (
            (df[self.heating_sig_col] == 0)
            & (df[self.cooling_sig_col] > 0)
            & (df[self.supply_vfd_speed_col] > 0)
            & (df[self.economizer_sig_col] == self.ahu_min_oa_dpr)
        )

        # Fill non-finite values with zero or drop them
        df = df.fillna(0)

        # Ensure boolean columns are integers
        df = df.astype(int)
        
        # Resample and apply function to count operating state changes
        df = df.resample("60min").apply(lambda x: (x.eq(1) & x.shift().ne(1)).sum())

        # Flag excessive operating state changes
        df["fc4_flag"] = df[df.columns].gt(self.delta_os_max).any(axis=1).astype(int)
        
        return df
