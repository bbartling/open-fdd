import pandas as pd

from open_fdd.core.base_fault import BaseFaultCondition
from open_fdd.core.components import FaultInputColumn, InstanceAttribute
from open_fdd.core.exceptions import InvalidParameterError, MissingColumnError
from open_fdd.core.mixins import FaultConditionMixin

INPUT_COLS = [
    FaultInputColumn(
        name="economizer_sig_col",
        constant_form="ECONOMIZER_SIG_COL",
        description="Economizer signal",
        unit="%",
        required=True,
        type=float,
    ),
    FaultInputColumn(
        name="heating_sig_col",
        constant_form="HEATING_SIG_COL",
        description="Heating signal",
        unit="%",
        required=False,
        type=float,
    ),
    FaultInputColumn(
        name="cooling_sig_col",
        constant_form="COOLING_SIG_COL",
        description="Cooling signal",
        unit="%",
        required=False,
        type=float,
    ),
    FaultInputColumn(
        name="supply_vfd_speed_col",
        constant_form="SUPPLY_VFD_SPEED_COL",
        description="Supply fan VFD speed",
        unit="%",
        required=True,
        type=float,
    ),
]

FAULT_PARAMS = [
    InstanceAttribute(
        name="delta_os_max",
        constant_form="DELTA_OS_MAX",
        description="Maximum allowable operating state changes",
        unit="count",
        type=int,
        range=(0, 100),
    ),
    InstanceAttribute(
        name="ahu_min_oa_dpr",
        constant_form="AHU_MIN_OA_DPR",
        description="Minimum outdoor air damper position",
        unit="fraction",
        type=float,
        range=(0.0, 1.0),
    ),
]


class FaultConditionFour(BaseFaultCondition, FaultConditionMixin):
    """Class provides the definitions for Fault Condition 4.

    This fault flags excessive operating states on the AHU
    if it's hunting between heating, econ, econ+mech, and
    a mech clg modes. The code counts how many operating
    changes in an hour and will throw a fault if there is
    excessive OS changes to flag control sys hunting.

    py -3.12 -m pytest open_fdd/tests/ahu/test_ahu_fc4.py -rP -s
    """

    input_columns = INPUT_COLS
    fault_params = FAULT_PARAMS
    equation_string = (
        "fc4_flag = 1 if excessive mode changes (> δOS_max) occur "
        "within an hour across heating, econ, econ+mech, mech clg, and min OA modes \n"
    )
    description_string = "Fault Condition 4: Excessive AHU operating state changes detected (hunting behavior) \n"
    error_string = "One or more required columns are missing or None \n"

    @FaultConditionMixin._handle_errors
    def apply(self, df: pd.DataFrame) -> pd.DataFrame:
        """Apply the fault condition to the DataFrame."""
        # Apply common checks
        self._apply_common_checks(df)

        # Get column values using accessor methods
        supply_vfd_speed_col = self.get_input_column("supply_vfd_speed_col")
        economizer_sig_col = self.get_input_column("economizer_sig_col")
        heating_sig_col = self.get_input_column("heating_sig_col")
        cooling_sig_col = self.get_input_column("cooling_sig_col")

        # Get parameter values using accessor methods
        delta_os_max = self.get_param("delta_os_max")
        ahu_min_oa_dpr = self.get_param("ahu_min_oa_dpr")

        # Add analog checks for supply_vfd_speed_col
        self._apply_analog_checks(
            df, [supply_vfd_speed_col], check_greater_than_one=True
        )

        # Convert VFD speed from percentage to fraction if needed
        if (df[supply_vfd_speed_col] > 1.0).any():
            df[supply_vfd_speed_col] = df[supply_vfd_speed_col] / 100.0

        # Calculate operating state changes
        df["os_change"] = 0
        df.loc[df[economizer_sig_col] > 0, "os_change"] += 1
        df.loc[df[supply_vfd_speed_col] > ahu_min_oa_dpr, "os_change"] += 1
        if heating_sig_col:
            df.loc[df[heating_sig_col] > 0, "os_change"] += 1
        if cooling_sig_col:
            df.loc[df[cooling_sig_col] > 0, "os_change"] += 1

        # Calculate changes in operating state
        df["os_change_diff"] = df["os_change"].diff().abs()
        df["os_change_diff"] = df["os_change_diff"].fillna(0)

        # Calculate rolling sum of changes
        df["os_change_sum"] = df["os_change_diff"].rolling(window=60).sum()

        # Set fault flag
        df["fc4_flag"] = (df["os_change_sum"] > delta_os_max).astype(int)

        return df
