import pandas as pd
import numpy as np
from open_fdd.core.base_fault import BaseFaultCondition
from open_fdd.core.mixins import FaultConditionMixin
from open_fdd.core.exceptions import InvalidParameterError

class FaultConditionFive(BaseFaultCondition, FaultConditionMixin):
    """Class provides the definitions for Fault Condition 5.
    SAT too low; should be higher than MAT in HTG MODE
    --Broken heating valve or other mechanical issue
    related to heat valve not working as designed
    """

    def _init_specific_attributes(self, dict_):
        # Threshold parameters
        self.mix_degf_err_thres = dict_.get("MIX_DEGF_ERR_THRES", None)
        self.supply_degf_err_thres = dict_.get("SUPPLY_DEGF_ERR_THRES", None)
        self.delta_t_supply_fan = dict_.get("DELTA_T_SUPPLY_FAN", None)

        # Validate that threshold parameters are floats
        for param, value in [
            ("mix_degf_err_thres", self.mix_degf_err_thres),
            ("supply_degf_err_thres", self.supply_degf_err_thres),
            ("delta_t_supply_fan", self.delta_t_supply_fan),
        ]:
            if not isinstance(value, float):
                raise InvalidParameterError(
                    f"The parameter '{param}' should be a float, but got {type(value).__name__}."
                )

        # Other attributes
        self.mat_col = dict_.get("MAT_COL", None)
        self.sat_col = dict_.get("SAT_COL", None)
        self.heating_sig_col = dict_.get("HEATING_SIG_COL", None)
        self.supply_vfd_speed_col = dict_.get("SUPPLY_VFD_SPEED_COL", None)

        # Set documentation strings
        self.equation_string = (
            "fc5_flag = 1 if (SAT + εSAT <= MAT - εMAT + ΔT_supply_fan) and "
            "(heating signal > 0) and (VFDSPD > 0) for N consecutive values else 0 \n"
        )
        self.description_string = (
            "Fault Condition 5: SAT too low; should be higher than MAT in HTG MODE, "
            "potential broken heating valve or mechanical issue \n"
        )
        self.required_column_description = (
            "Required inputs are the mixed air temperature, supply air temperature, "
            "heating signal, and supply fan VFD speed \n"
        )
        self.error_string = "One or more required columns are missing or None \n"

        # Set required columns specific to this fault condition
        self.required_columns = [
            self.mat_col,
            self.sat_col,
            self.heating_sig_col,
            self.supply_vfd_speed_col,
        ]

    @FaultConditionMixin._handle_errors
    def apply(self, df: pd.DataFrame) -> pd.DataFrame:
        """Apply the fault condition to the DataFrame."""
        # Apply common checks
        self._apply_common_checks(df)

        # Check analog outputs [data with units of %] are floats only
        columns_to_check = [self.supply_vfd_speed_col, self.heating_sig_col]
        self._apply_analog_checks(df, columns_to_check)

        # Perform checks
        sat_check = df[self.sat_col] + self.supply_degf_err_thres
        mat_check = df[self.mat_col] - self.mix_degf_err_thres + self.delta_t_supply_fan

        combined_check = (
            (sat_check <= mat_check)
            & (df[self.heating_sig_col] > 0.01)
            & (df[self.supply_vfd_speed_col] > 0.01)
        )

        # Set fault flag
        self._set_fault_flag(df, combined_check, "fc5_flag")

        return df