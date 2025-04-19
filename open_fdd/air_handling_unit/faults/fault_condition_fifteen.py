
import pandas as pd
import pandas as pd
import numpy as np
from open_fdd.core.base_fault import BaseFaultCondition
from open_fdd.core.mixins import FaultConditionMixin
import sys
from open_fdd.core.exceptions import MissingColumnError, InvalidParameterError
from open_fdd.core.base_fault import BaseFaultCondition
from open_fdd.core.mixins import FaultConditionMixin
class FaultConditionFifteen(BaseFaultCondition, FaultConditionMixin):
    """Class provides the definitions for Fault Condition 15.
    Temperature rise across inactive heating coil in OS2 (economizer),
    OS3 (economizer + mechanical cooling), and OS4 (mechanical cooling only) modes.
    This fault checks if there is an unexpected temperature rise across the heating coil
    when it should be inactive.

    py -3.12 -m pytest open_fdd/tests/ahu/test_ahu_fc15.py -rP -s
    """

    def _init_specific_attributes(self, dict_):
        # Threshold parameters
        self.delta_t_supply_fan = dict_.get("DELTA_SUPPLY_FAN", None)
        self.coil_temp_enter_err_thres = dict_.get("COIL_TEMP_ENTER_ERR_THRES", None)
        self.coil_temp_leave_err_thres = dict_.get("COIL_TEMP_LEAV_ERR_THRES", None)
        self.ahu_min_oa_dpr = dict_.get("AHU_MIN_OA_DPR", None)

        # Validate that threshold parameters are floats
        for param, value in [
            ("delta_t_supply_fan", self.delta_t_supply_fan),
            ("coil_temp_enter_err_thres", self.coil_temp_enter_err_thres),
            ("coil_temp_leave_err_thres", self.coil_temp_leave_err_thres),
            ("ahu_min_oa_dpr", self.ahu_min_oa_dpr),
        ]:
            if not isinstance(value, float):
                raise InvalidParameterError(
                    f"The parameter '{param}' should be a float, but got {type(value).__name__}."
                )

        # Other attributes
        self.htg_coil_enter_temp_col = dict_.get("HTG_COIL_ENTER_TEMP_COL", None)
        self.htg_coil_leave_temp_col = dict_.get("HTG_COIL_LEAVE_TEMP_COL", None)
        self.cooling_sig_col = dict_.get("COOLING_SIG_COL", None)
        self.heating_sig_col = dict_.get("HEATING_SIG_COL", None)
        self.economizer_sig_col = dict_.get("ECONOMIZER_SIG_COL", None)
        self.supply_vfd_speed_col = dict_.get("SUPPLY_VFD_SPEED_COL", None)

        # Set documentation strings
        self.equation_string = (
            "fc15_flag = 1 if (HTG_LEAVE > HTG_ENTER + √(εENTER² + εLEAVE²) + ΔTfan) "
            "in OS2 (economizer), OS3 (economizer + mechanical cooling), or "
            "OS4 (mechanical cooling only) modes for N consecutive values else 0 \n"
        )
        self.description_string = (
            "Fault Condition 15: Temperature rise across inactive heating coil "
            "in OS2 (economizer), OS3 (economizer + mechanical cooling), and "
            "OS4 (mechanical cooling only) modes \n"
        )
        self.required_column_description = (
            "Required inputs are the heating coil entering and leaving air temperatures, "
            "cooling signal, heating signal, economizer signal, and supply fan VFD speed \n"
        )
        self.error_string = "One or more required columns are missing or None \n"

        # Set required columns specific to this fault condition
        self.required_columns = [
            self.htg_coil_enter_temp_col,
            self.htg_coil_leave_temp_col,
            self.cooling_sig_col,
            self.heating_sig_col,
            self.economizer_sig_col,
            self.supply_vfd_speed_col,
        ]

    @FaultConditionMixin._handle_errors
    def apply(self, df: pd.DataFrame) -> pd.DataFrame:
        """Apply the fault condition to the DataFrame."""
        # Apply common checks
        self._apply_common_checks(df)

        # Check analog outputs [data with units of %] are floats only
        columns_to_check = [
            self.cooling_sig_col,
            self.heating_sig_col,
            self.economizer_sig_col,
            self.supply_vfd_speed_col,
        ]
        self._apply_analog_checks(df, columns_to_check)

        # Calculate the threshold for temperature rise, including supply fan heat
        temp_rise_threshold = (
            np.sqrt(
                self.coil_temp_enter_err_thres**2 + self.coil_temp_leave_err_thres**2
            )
            + self.delta_t_supply_fan
        )

        # Check if there's a significant temperature rise across the heating coil
        temp_rise = df[self.htg_coil_leave_temp_col] - df[self.htg_coil_enter_temp_col]
        significant_temp_rise = temp_rise > temp_rise_threshold

        # Check operating modes:
        # OS2: Economizer mode (HTG = 0, CLG = 0, ECO > MIN_OA)
        os2_mode = (
            (df[self.heating_sig_col] == 0.0)
            & (df[self.cooling_sig_col] == 0.0)
            & (df[self.economizer_sig_col] > self.ahu_min_oa_dpr)
        )

        # OS3: Economizer + mechanical cooling (HTG = 0, CLG > 0, ECO > 0.9)
        os3_mode = (
            (df[self.heating_sig_col] == 0.0)
            & (df[self.cooling_sig_col] > 0.0)
            & (df[self.economizer_sig_col] > 0.9)
        )

        # OS4: Mechanical cooling only (HTG = 0, CLG > 0, ECO = MIN_OA)
        os4_mode = (
            (df[self.heating_sig_col] == 0.0)
            & (df[self.cooling_sig_col] > 0.0)
            & (df[self.economizer_sig_col] <= self.ahu_min_oa_dpr)
        )

        # Combine conditions:
        # Fault occurs when there's a significant temperature rise across an inactive heating coil
        # in OS2 (economizer), OS3 (economizer + mechanical cooling), or OS4 (mechanical cooling only) mode
        combined_check = significant_temp_rise & (os2_mode | os3_mode | os4_mode)

        # Set fault flag
        self._set_fault_flag(df, combined_check, "fc15_flag")

        return df
