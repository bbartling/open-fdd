import pandas as pd
import pandas as pd
import numpy as np
from open_fdd.core.base_fault import BaseFaultCondition
from open_fdd.core.mixins import FaultConditionMixin
import sys
from open_fdd.core.exceptions import MissingColumnError, InvalidParameterError
from open_fdd.core.base_fault import BaseFaultCondition
from open_fdd.core.mixins import FaultConditionMixin

class FaultConditionNine(BaseFaultCondition, FaultConditionMixin):
    """Class provides the definitions for Fault Condition 9.
    Outside air temperature too high in free cooling without
    additional mechanical cooling in economizer mode.

    py -3.12 -m pytest open_fdd/tests/ahu/test_ahu_fc9.py -rP -s
    """

    def _init_specific_attributes(self, dict_):
        # Threshold parameters
        self.delta_t_supply_fan = dict_.get("DELTA_T_SUPPLY_FAN", None)
        self.outdoor_degf_err_thres = dict_.get("OUTDOOR_DEGF_ERR_THRES", None)
        self.supply_degf_err_thres = dict_.get("SUPPLY_DEGF_ERR_THRES", None)
        self.ahu_min_oa_dpr = dict_.get("AHU_MIN_OA_DPR", None)

        # Validate that threshold parameters are floats
        for param, value in [
            ("delta_t_supply_fan", self.delta_t_supply_fan),
            ("outdoor_degf_err_thres", self.outdoor_degf_err_thres),
            ("supply_degf_err_thres", self.supply_degf_err_thres),
            ("ahu_min_oa_dpr", self.ahu_min_oa_dpr),
        ]:
            if not isinstance(value, float):
                raise InvalidParameterError(
                    f"The parameter '{param}' should be a float, but got {type(value).__name__}."
                )

        # Other attributes
        self.sat_setpoint_col = dict_.get("SAT_SETPOINT_COL", None)
        self.oat_col = dict_.get("OAT_COL", None)
        self.cooling_sig_col = dict_.get("COOLING_SIG_COL", None)
        self.economizer_sig_col = dict_.get("ECONOMIZER_SIG_COL", None)

        # Set documentation strings
        self.equation_string = (
            "fc9_flag = 1 if OAT > (SATSP - ΔT_fan + εSAT) "
            "in free cooling mode for N consecutive values else 0 \n"
        )
        self.description_string = (
            "Fault Condition 9: Outside air temperature too high in free cooling mode "
            "without additional mechanical cooling in economizer mode \n"
        )
        self.required_column_description = (
            "Required inputs are the supply air temperature setpoint, outside air temperature, "
            "cooling signal, and economizer signal \n"
        )
        self.error_string = "One or more required columns are missing or None \n"

        # Set required columns specific to this fault condition
        self.required_columns = [
            self.sat_setpoint_col,
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

        # Perform calculations
        oat_minus_oaterror = df[self.oat_col] - self.outdoor_degf_err_thres
        satsp_delta_saterr = (
            df[self.sat_setpoint_col]
            - self.delta_t_supply_fan
            + self.supply_degf_err_thres
        )

        combined_check = (
            (oat_minus_oaterror > satsp_delta_saterr)
            # verify AHU is in OS2 only free cooling mode
            & (df[self.economizer_sig_col] > self.ahu_min_oa_dpr)
            & (df[self.cooling_sig_col] < 0.1)
        )

        # Set fault flag
        self._set_fault_flag(df, combined_check, "fc9_flag")

        return df