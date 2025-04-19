
import pandas as pd
import pandas as pd
import numpy as np
from open_fdd.core.base_fault import BaseFaultCondition
from open_fdd.core.mixins import FaultConditionMixin
import sys
from open_fdd.core.exceptions import MissingColumnError, InvalidParameterError
from open_fdd.core.base_fault import BaseFaultCondition
from open_fdd.core.mixins import FaultConditionMixin
class FaultConditionThirteen(BaseFaultCondition, FaultConditionMixin):
    """Class provides the definitions for Fault Condition 13.
    Supply air temperature too high in full cooling mode.
    This fault checks if SAT is too high compared to SAT setpoint
    in OS3 (economizer + mechanical cooling) and OS4 (mechanical cooling only) modes.

    py -3.12 -m pytest open_fdd/tests/ahu/test_ahu_fc13.py -rP -s
    """

    def _init_specific_attributes(self, dict_):
        # Threshold parameters
        self.supply_degf_err_thres = dict_.get("SUPPLY_DEGF_ERR_THRES", None)
        self.mix_degf_err_thres = dict_.get("MIX_DEGF_ERR_THRES", None)
        self.outdoor_degf_err_thres = dict_.get("OUTDOOR_DEGF_ERR_THRES", None)
        self.ahu_min_oa_dpr = dict_.get("AHU_MIN_OA_DPR", None)

        # Validate that threshold parameters are floats
        for param, value in [
            ("supply_degf_err_thres", self.supply_degf_err_thres),
            ("mix_degf_err_thres", self.mix_degf_err_thres),
            ("outdoor_degf_err_thres", self.outdoor_degf_err_thres),
            ("ahu_min_oa_dpr", self.ahu_min_oa_dpr),
        ]:
            if not isinstance(value, float):
                raise InvalidParameterError(
                    f"The parameter '{param}' should be a float, but got {type(value).__name__}."
                )

        # Other attributes
        self.sat_col = dict_.get("SAT_COL", None)
        self.sat_sp_col = dict_.get("SAT_SP_COL", None)
        self.cooling_sig_col = dict_.get("COOLING_SIG_COL", None)
        self.economizer_sig_col = dict_.get("ECONOMIZER_SIG_COL", None)

        # Set documentation strings
        self.equation_string = (
            "fc13_flag = 1 if (SAT > SATSP + εSAT) and "
            "((CLG > 0.9 and ECO > 0.9) or (CLG > 0.9 and ECO = MIN_OA)) "
            "for N consecutive values else 0 \n"
        )
        self.description_string = (
            "Fault Condition 13: Supply air temperature too high in full cooling mode "
            "in OS3 (economizer + mechanical cooling) and OS4 (mechanical cooling only) modes \n"
        )
        self.required_column_description = (
            "Required inputs are the supply air temperature, supply air temperature setpoint, "
            "cooling signal, and economizer signal \n"
        )
        self.error_string = "One or more required columns are missing or None \n"

        # Set required columns specific to this fault condition
        self.required_columns = [
            self.sat_col,
            self.sat_sp_col,
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

        # Check if SAT is too high compared to setpoint
        sat_too_high = df[self.sat_col] > (
            df[self.sat_sp_col] + self.supply_degf_err_thres
        )

        # Check operating modes:
        # OS3: Economizer + full mechanical cooling (ECO > 0.9 and CLG > 0.9)
        os3_mode = (df[self.economizer_sig_col] > 0.9) & (
            df[self.cooling_sig_col] > 0.9
        )

        # OS4: Full mechanical cooling only (ECO = MIN_OA and CLG > 0.9)
        os4_mode = (df[self.economizer_sig_col] <= self.ahu_min_oa_dpr) & (
            df[self.cooling_sig_col] > 0.9
        )

        # Combine conditions:
        # Fault occurs when SAT is too high in either OS3 or OS4 mode with full cooling
        combined_check = sat_too_high & (os3_mode | os4_mode)

        # Set fault flag
        self._set_fault_flag(df, combined_check, "fc13_flag")

        return df