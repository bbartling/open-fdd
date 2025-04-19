import pandas as pd
import numpy as np
from open_fdd.core.base_fault import BaseFaultCondition
from open_fdd.core.mixins import FaultConditionMixin
import sys
from open_fdd.core.exceptions import MissingColumnError, InvalidParameterError

class FaultConditionSixteen(BaseFaultCondition, FaultConditionMixin):
    """Class provides the definitions for Fault Condition 16.
    ERV effectiveness should be within specified thresholds based on OAT.
    This fault checks if the ERV (Energy Recovery Ventilator) is operating
    within expected efficiency ranges in both heating and cooling modes.

    py -3.12 -m pytest open_fdd/tests/ahu/test_ahu_fc16.py -rP -s
    """

    def _init_specific_attributes(self, dict_):
        # Threshold parameters
        self.erv_efficiency_min_heating = dict_.get("ERV_EFFICIENCY_MIN_HEATING", None)
        self.erv_efficiency_max_heating = dict_.get("ERV_EFFICIENCY_MAX_HEATING", None)
        self.erv_efficiency_min_cooling = dict_.get("ERV_EFFICIENCY_MIN_COOLING", None)
        self.erv_efficiency_max_cooling = dict_.get("ERV_EFFICIENCY_MAX_COOLING", None)
        self.oat_low_threshold = dict_.get("OAT_LOW_THRESHOLD", None)
        self.oat_high_threshold = dict_.get("OAT_HIGH_THRESHOLD", None)
        self.oat_rat_delta_min = dict_.get("OAT_RAT_DELTA_MIN", None)

        # Validate that threshold parameters are floats
        for param, value in [
            ("erv_efficiency_min_heating", self.erv_efficiency_min_heating),
            ("erv_efficiency_max_heating", self.erv_efficiency_max_heating),
            ("erv_efficiency_min_cooling", self.erv_efficiency_min_cooling),
            ("erv_efficiency_max_cooling", self.erv_efficiency_max_cooling),
            ("oat_low_threshold", self.oat_low_threshold),
            ("oat_high_threshold", self.oat_high_threshold),
            ("oat_rat_delta_min", self.oat_rat_delta_min),
        ]:
            if not isinstance(value, float):
                raise InvalidParameterError(
                    f"The parameter '{param}' should be a float, but got {type(value).__name__}."
                )

        # Validate that efficiency values are between 0.0 and 1.0
        for param, value in [
            ("ERV_EFFICIENCY_MIN_HEATING", self.erv_efficiency_min_heating),
            ("ERV_EFFICIENCY_MAX_HEATING", self.erv_efficiency_max_heating),
            ("ERV_EFFICIENCY_MIN_COOLING", self.erv_efficiency_min_cooling),
            ("ERV_EFFICIENCY_MAX_COOLING", self.erv_efficiency_max_cooling),
        ]:
            if not 0.0 <= value <= 1.0:
                raise InvalidParameterError(
                    f"The parameter '{param}' should be a float between 0.0 and 1.0, but got {value}."
                )

        # Other attributes
        self.erv_oat_enter_col = dict_.get("ERV_OAT_ENTER_COL", None)
        self.erv_oat_leaving_col = dict_.get("ERV_OAT_LEAVING_COL", None)
        self.erv_eat_enter_col = dict_.get("ERV_EAT_ENTER_COL", None)
        self.erv_eat_leaving_col = dict_.get("ERV_EAT_LEAVING_COL", None)
        self.supply_vfd_speed_col = dict_.get("SUPPLY_VFD_SPEED_COL", None)

        # Set documentation strings
        self.equation_string = (
            "fc16_flag = 1 if ERV effectiveness is outside expected range "
            "(heating: εmin_htg ≤ ε ≤ εmax_htg, cooling: εmin_clg ≤ ε ≤ εmax_clg) "
            "for N consecutive values else 0 \n"
        )
        self.description_string = (
            "Fault Condition 16: ERV effectiveness should be within specified "
            "thresholds based on OAT \n"
        )
        self.required_column_description = (
            "Required inputs are the ERV outdoor air entering and leaving temperatures, "
            "ERV exhaust air entering and leaving temperatures, and supply fan VFD speed \n"
        )
        self.error_string = "One or more required columns are missing or None \n"

        # Set required columns specific to this fault condition
        self.required_columns = [
            self.erv_oat_enter_col,
            self.erv_oat_leaving_col,
            self.erv_eat_enter_col,
            self.erv_eat_leaving_col,
            self.supply_vfd_speed_col,
        ]

    @FaultConditionMixin._handle_errors
    def apply(self, df: pd.DataFrame) -> pd.DataFrame:
        """Apply the fault condition to the DataFrame."""
        # Apply common checks
        self._apply_common_checks(df)

        # Check analog outputs [data with units of %] are floats only
        columns_to_check = [self.supply_vfd_speed_col]
        self._apply_analog_checks(df, columns_to_check)

        # Calculate temperature differences
        oat_rat_delta = abs(df[self.erv_oat_enter_col] - df[self.erv_eat_enter_col])

        # Calculate ERV effectiveness
        # ε = (T_leaving - T_entering) / (T_exhaust - T_entering)
        erv_effectiveness = (
            df[self.erv_oat_leaving_col] - df[self.erv_oat_enter_col]
        ) / (df[self.erv_eat_enter_col] - df[self.erv_oat_enter_col])

        # Determine operating mode based on OAT
        heating_mode = df[self.erv_oat_enter_col] < self.oat_low_threshold
        cooling_mode = df[self.erv_oat_enter_col] > self.oat_high_threshold

        # Check effectiveness against thresholds
        low_effectiveness_htg = heating_mode & (
            erv_effectiveness < self.erv_efficiency_min_heating
        )
        high_effectiveness_htg = heating_mode & (
            erv_effectiveness > self.erv_efficiency_max_heating
        )
        low_effectiveness_clg = cooling_mode & (
            erv_effectiveness < self.erv_efficiency_min_cooling
        )
        high_effectiveness_clg = cooling_mode & (
            erv_effectiveness > self.erv_efficiency_max_cooling
        )

        # Combine conditions:
        # Fault occurs when ERV effectiveness is outside expected range
        # and there's sufficient temperature difference between OAT and RAT
        combined_check = (oat_rat_delta >= self.oat_rat_delta_min) & (
            low_effectiveness_htg
            | high_effectiveness_htg
            | low_effectiveness_clg
            | high_effectiveness_clg
        )

        # Set fault flag
        self._set_fault_flag(df, combined_check, "fc16_flag")

        return df
