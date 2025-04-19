
import sys

import numpy as np
import pandas as pd

from open_fdd.core.base_fault import BaseFaultCondition
from open_fdd.core.exceptions import InvalidParameterError
from open_fdd.core.mixins import FaultConditionMixin


class FaultConditionEleven(BaseFaultCondition, FaultConditionMixin):
    """Class provides the definitions for Fault Condition 11.
    Outdoor air temperature and mix air temperature should
    be approx equal in economizer mode.

    py -3.12 -m pytest open_fdd/tests/ahu/test_ahu_fc11.py -rP -s
    """

    def _init_specific_attributes(self, dict_):
        # Threshold parameters
        self.outdoor_degf_err_thres = dict_.get("OUTDOOR_DEGF_ERR_THRES", None)
        self.mix_degf_err_thres = dict_.get("MIX_DEGF_ERR_THRES", None)

        # Validate that threshold parameters are floats
        for param, value in [
            ("outdoor_degf_err_thres", self.outdoor_degf_err_thres),
            ("mix_degf_err_thres", self.mix_degf_err_thres),
        ]:
            if not isinstance(value, float):
                raise InvalidParameterError(
                    f"The parameter '{param}' should be a float, but got {type(value).__name__}."
                )

        # Other attributes
        self.oat_col = dict_.get("OAT_COL", None)
        self.mat_col = dict_.get("MAT_COL", None)
        self.economizer_sig_col = dict_.get("ECONOMIZER_SIG_COL", None)

        # Set documentation strings
        self.equation_string = (
            "fc11_flag = 1 if |OAT - MAT| > √(εOAT² + εMAT²) in "
            "economizer mode for N consecutive values else 0 \n"
        )
        self.description_string = (
            "Fault Condition 11: Outdoor air temperature and mixed air temperature "
            "should be approximately equal in economizer mode \n"
        )
        self.required_column_description = (
            "Required inputs are the outside air temperature, mixed air temperature, "
            "and economizer signal \n"
        )
        self.error_string = "One or more required columns are missing or None \n"

        # Set required columns specific to this fault condition
        self.required_columns = [
            self.oat_col,
            self.mat_col,
            self.economizer_sig_col,
        ]

    @FaultConditionMixin._handle_errors
    def apply(self, df: pd.DataFrame) -> pd.DataFrame:
        """Apply the fault condition to the DataFrame."""
        # Apply common checks
        self._apply_common_checks(df)

        # Check analog outputs [data with units of %] are floats only
        columns_to_check = [self.economizer_sig_col]
        self._apply_analog_checks(df, columns_to_check)

        # Perform calculations
        abs_mat_minus_oat = abs(df[self.mat_col] - df[self.oat_col])
        mat_oat_sqrted = np.sqrt(
            self.mix_degf_err_thres**2 + self.outdoor_degf_err_thres**2
        )

        combined_check = (
            (abs_mat_minus_oat > mat_oat_sqrted)
            # Verify AHU is running in economizer mode
            & (df[self.economizer_sig_col] > 0.9)
        )

        # Set fault flag
        self._set_fault_flag(df, combined_check, "fc11_flag")

        return df