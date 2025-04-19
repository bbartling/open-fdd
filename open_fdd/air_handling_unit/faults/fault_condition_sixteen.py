import numpy as np
import pandas as pd

from open_fdd.core.base_fault import BaseFaultCondition
from open_fdd.core.components import FaultInputColumn, InstanceAttribute
from open_fdd.core.exceptions import InvalidParameterError
from open_fdd.core.mixins import FaultConditionMixin

INPUT_COLS = [
    FaultInputColumn(
        name="erv_oat_enter_col",
        constant_form="ERV_OAT_ENTER_COL",
        description="ERV outdoor air entering temperature",
        unit="°F",
        required=True,
        type=float,
    ),
    FaultInputColumn(
        name="erv_oat_leaving_col",
        constant_form="ERV_OAT_LEAVING_COL",
        description="ERV outdoor air leaving temperature",
        unit="°F",
        required=True,
        type=float,
    ),
    FaultInputColumn(
        name="erv_eat_enter_col",
        constant_form="ERV_EAT_ENTER_COL",
        description="ERV exhaust air entering temperature",
        unit="°F",
        required=True,
        type=float,
    ),
    FaultInputColumn(
        name="erv_eat_leaving_col",
        constant_form="ERV_EAT_LEAVING_COL",
        description="ERV exhaust air leaving temperature",
        unit="°F",
        required=True,
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
        name="erv_efficiency_min_heating",
        constant_form="ERV_EFFICIENCY_MIN_HEATING",
        description="Minimum expected ERV efficiency in heating mode",
        unit="fraction",
        type=float,
        range=(0.0, 1.0),
    ),
    InstanceAttribute(
        name="erv_efficiency_max_heating",
        constant_form="ERV_EFFICIENCY_MAX_HEATING",
        description="Maximum expected ERV efficiency in heating mode",
        unit="fraction",
        type=float,
        range=(0.0, 1.0),
    ),
    InstanceAttribute(
        name="erv_efficiency_min_cooling",
        constant_form="ERV_EFFICIENCY_MIN_COOLING",
        description="Minimum expected ERV efficiency in cooling mode",
        unit="fraction",
        type=float,
        range=(0.0, 1.0),
    ),
    InstanceAttribute(
        name="erv_efficiency_max_cooling",
        constant_form="ERV_EFFICIENCY_MAX_COOLING",
        description="Maximum expected ERV efficiency in cooling mode",
        unit="fraction",
        type=float,
        range=(0.0, 1.0),
    ),
    InstanceAttribute(
        name="oat_low_threshold",
        constant_form="OAT_LOW_THRESHOLD",
        description="OAT threshold for heating mode",
        unit="°F",
        type=float,
    ),
    InstanceAttribute(
        name="oat_high_threshold",
        constant_form="OAT_HIGH_THRESHOLD",
        description="OAT threshold for cooling mode",
        unit="°F",
        type=float,
    ),
    InstanceAttribute(
        name="oat_rat_delta_min",
        constant_form="OAT_RAT_DELTA_MIN",
        description="Minimum required delta between OAT and RAT",
        unit="°F",
        type=float,
    ),
]


class FaultConditionSixteen(BaseFaultCondition, FaultConditionMixin):
    """Class provides the definitions for Fault Condition 16.
    ERV effectiveness should be within specified thresholds based on OAT.
    This fault checks if the ERV (Energy Recovery Ventilator) is operating
    within expected efficiency ranges in both heating and cooling modes.

    py -3.12 -m pytest open_fdd/tests/ahu/test_ahu_fc16.py -rP -s
    """

    input_columns = INPUT_COLS
    fault_params = FAULT_PARAMS
    equation_string = (
        "fc16_flag = 1 if ERV effectiveness is outside expected range "
        "(heating: εmin_htg ≤ ε ≤ εmax_htg, cooling: εmin_clg ≤ ε ≤ εmax_clg) "
        "for N consecutive values else 0 \n"
    )
    description_string = (
        "Fault Condition 16: ERV effectiveness should be within specified "
        "thresholds based on OAT \n"
    )
    error_string = "One or more required columns are missing or None \n"

    @FaultConditionMixin._handle_errors
    def apply(self, df: pd.DataFrame) -> pd.DataFrame:
        """Apply the fault condition to the DataFrame."""
        # Apply common checks
        self._apply_common_checks(df)

        # Get column values using accessor methods
        supply_vfd_speed_col = self.get_input_column("supply_vfd_speed_col")
        erv_oat_enter_col = self.get_input_column("erv_oat_enter_col")
        erv_oat_leaving_col = self.get_input_column("erv_oat_leaving_col")
        erv_eat_enter_col = self.get_input_column("erv_eat_enter_col")

        # Get parameter values using accessor methods
        erv_efficiency_min_heating = self.get_param("erv_efficiency_min_heating")
        erv_efficiency_max_heating = self.get_param("erv_efficiency_max_heating")
        erv_efficiency_min_cooling = self.get_param("erv_efficiency_min_cooling")
        erv_efficiency_max_cooling = self.get_param("erv_efficiency_max_cooling")
        oat_low_threshold = self.get_param("oat_low_threshold")
        oat_high_threshold = self.get_param("oat_high_threshold")
        oat_rat_delta_min = self.get_param("oat_rat_delta_min")

        # Check analog outputs [data with units of %] are floats only
        columns_to_check = [supply_vfd_speed_col]
        self._apply_analog_checks(df, columns_to_check, check_greater_than_one=True)

        # Calculate temperature differences
        oat_rat_delta = abs(df[erv_oat_enter_col] - df[erv_eat_enter_col])

        # Calculate ERV effectiveness
        # ε = (T_leaving - T_entering) / (T_exhaust - T_entering)
        erv_effectiveness = (df[erv_oat_leaving_col] - df[erv_oat_enter_col]) / (
            df[erv_eat_enter_col] - df[erv_oat_enter_col]
        )

        # Determine operating mode based on OAT
        heating_mode = df[erv_oat_enter_col] < oat_low_threshold
        cooling_mode = df[erv_oat_enter_col] > oat_high_threshold

        # Check effectiveness against thresholds
        low_effectiveness_htg = heating_mode & (
            erv_effectiveness < erv_efficiency_min_heating
        )
        high_effectiveness_htg = heating_mode & (
            erv_effectiveness > erv_efficiency_max_heating
        )
        low_effectiveness_clg = cooling_mode & (
            erv_effectiveness < erv_efficiency_min_cooling
        )
        high_effectiveness_clg = cooling_mode & (
            erv_effectiveness > erv_efficiency_max_cooling
        )

        # Combine conditions:
        # Fault occurs when ERV effectiveness is outside expected range
        # and there's sufficient temperature difference between OAT and RAT
        combined_check = (oat_rat_delta >= oat_rat_delta_min) & (
            low_effectiveness_htg
            | high_effectiveness_htg
            | low_effectiveness_clg
            | high_effectiveness_clg
        )

        # Set fault flag
        self._set_fault_flag(df, combined_check, "fc16_flag")

        return df
