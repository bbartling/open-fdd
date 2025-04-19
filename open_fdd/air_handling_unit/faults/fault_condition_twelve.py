
import pandas as pd
import pandas as pd
import numpy as np
from open_fdd.core.base_fault import BaseFaultCondition
from open_fdd.core.mixins import FaultConditionMixin
import sys
from open_fdd.core.exceptions import MissingColumnError, InvalidParameterError
from open_fdd.core.base_fault import BaseFaultCondition
from open_fdd.core.mixins import FaultConditionMixin
class FaultConditionTwelve(BaseFaultCondition, FaultConditionMixin):
    """Class provides the definitions for Fault Condition 12.
    Supply air temperature too high; should be less than mixed air temperature
    in OS3 (economizer + mechanical cooling) and OS4 (mechanical cooling only) modes.

    py -3.12 -m pytest open_fdd/tests/ahu/test_ahu_fc12.py -rP -s
    """

    def _init_specific_attributes(self, dict_):
        # Threshold parameters
        self.delta_t_supply_fan = dict_.get("DELTA_T_SUPPLY_FAN", None)
        self.mix_degf_err_thres = dict_.get("MIX_DEGF_ERR_THRES", None)
        self.supply_degf_err_thres = dict_.get("SUPPLY_DEGF_ERR_THRES", None)
        self.outdoor_degf_err_thres = dict_.get("OUTDOOR_DEGF_ERR_THRES", None)
        self.ahu_min_oa_dpr = dict_.get("AHU_MIN_OA_DPR", None)

        # Validate that threshold parameters are floats
        for param, value in [
            ("delta_t_supply_fan", self.delta_t_supply_fan),
            ("mix_degf_err_thres", self.mix_degf_err_thres),
            ("supply_degf_err_thres", self.supply_degf_err_thres),
            ("outdoor_degf_err_thres", self.outdoor_degf_err_thres),
            ("ahu_min_oa_dpr", self.ahu_min_oa_dpr),
        ]:
            if not isinstance(value, float):
                raise InvalidParameterError(
                    f"The parameter '{param}' should be a float, but got {type(value).__name__}."
                )

        # Other attributes
        self.sat_col = dict_.get("SAT_COL", None)
        self.mat_col = dict_.get("MAT_COL", None)
        self.oat_col = dict_.get("OAT_COL", None)
        self.cooling_sig_col = dict_.get("COOLING_SIG_COL", None)
        self.economizer_sig_col = dict_.get("ECONOMIZER_SIG_COL", None)

        # Set documentation strings
        self.equation_string = (
            "fc12_flag = 1 if (SAT > MAT + εSAT) and "
            "((CLG > 0 and ECO > 0.9) or (CLG > 0.9 and ECO = MIN_OA)) "
            "for N consecutive values else 0 \n"
        )
        self.description_string = (
            "Fault Condition 12: Supply air temperature too high; should be less than "
            "mixed air temperature in OS3 (economizer + mechanical cooling) and "
            "OS4 (mechanical cooling only) modes \n"
        )
        self.required_column_description = (
            "Required inputs are the supply air temperature, mixed air temperature, "
            "outside air temperature, cooling signal, and economizer signal \n"
        )
        self.error_string = "One or more required columns are missing or None \n"

        # Set required columns specific to this fault condition
        self.required_columns = [
            self.sat_col,
            self.mat_col,
            self.oat_col,
            self.cooling_sig_col,
            self.economizer_sig_col,
        ]

    @FaultConditionMixin._handle_errors
    def apply(self, df: pd.DataFrame) -> pd.DataFrame:
        """Apply the fault condition to the DataFrame."""
        # Apply common checks
        self._apply_common_checks(df)

        # Check analog outputs [data with units of %] are floats only
        columns_to_check = [
            self.economizer_sig_col,
            self.cooling_sig_col,
        ]
        self._apply_analog_checks(df, columns_to_check)

        # Calculate the threshold for SAT vs MAT comparison
        sat_mat_threshold = np.sqrt(
            self.supply_degf_err_thres**2 + self.mix_degf_err_thres**2
        )

        # Check if SAT is too high compared to MAT (accounting for supply fan heat)
        sat_too_high = df[self.sat_col] > (
            df[self.mat_col] + sat_mat_threshold + self.delta_t_supply_fan
        )

        # Check operating modes:
        # OS3: Economizer + mechanical cooling (ECO > 0.9 and CLG > 0)
        os3_mode = (df[self.economizer_sig_col] > 0.9) & (df[self.cooling_sig_col] > 0)

        # OS4: Mechanical cooling only (ECO = MIN_OA and CLG > 0.9)
        os4_mode = (df[self.economizer_sig_col] <= self.ahu_min_oa_dpr) & (
            df[self.cooling_sig_col] > 0.9
        )

        # Combine conditions:
        # Fault occurs when SAT is too high in either OS3 or OS4 mode
        combined_check = sat_too_high & (os3_mode | os4_mode)

        # Set fault flag
        self._set_fault_flag(df, combined_check, "fc12_flag")

        return df