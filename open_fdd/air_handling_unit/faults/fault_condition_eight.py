import pandas as pd
import numpy as np
from open_fdd.core.exceptions import MissingColumnError, InvalidParameterError
from open_fdd.core.base_fault import BaseFaultCondition
from open_fdd.core.mixins import FaultConditionMixin


class FaultConditionEight(BaseFaultCondition, FaultConditionMixin):
    """Class provides the definitions for Fault Condition 8.
    Supply air temperature and mix air temperature should
    be approx equal in economizer mode.

    py -3.12 -m pytest open_fdd/tests/ahu/test_ahu_fc8.py -rP -s
    """

    def _init_specific_attributes(self, dict_):
        # Threshold parameters
        self.delta_t_supply_fan = dict_.get("DELTA_T_SUPPLY_FAN", None)
        self.mix_degf_err_thres = dict_.get("MIX_DEGF_ERR_THRES", None)
        self.supply_degf_err_thres = dict_.get("SUPPLY_DEGF_ERR_THRES", None)
        self.ahu_min_oa_dpr = dict_.get("AHU_MIN_OA_DPR", None)

        # Validate that threshold parameters are floats
        for param, value in [
            ("delta_t_supply_fan", self.delta_t_supply_fan),
            ("mix_degf_err_thres", self.mix_degf_err_thres),
            ("supply_degf_err_thres", self.supply_degf_err_thres),
            ("ahu_min_oa_dpr", self.ahu_min_oa_dpr),
        ]:
            if not isinstance(value, float):
                raise InvalidParameterError(
                    f"The parameter '{param}' should be a float, but got {type(value).__name__}."
                )

        # Other attributes
        self.mat_col = dict_.get("MAT_COL", None)
        self.sat_col = dict_.get("SAT_COL", None)
        self.economizer_sig_col = dict_.get("ECONOMIZER_SIG_COL", None)
        self.cooling_sig_col = dict_.get("COOLING_SIG_COL", None)

        # Set documentation strings
        self.equation_string = (
            "fc8_flag = 1 if |SAT - MAT - ΔT_fan| > √(εSAT² + εMAT²) "
            "in economizer mode for N consecutive values else 0 \n"
        )
        self.description_string = (
            "Fault Condition 8: Supply air temperature and mixed air temperature should "
            "be approximately equal in economizer mode \n"
        )
        self.required_column_description = (
            "Required inputs are the mixed air temperature, supply air temperature, "
            "economizer signal, and cooling signal \n"
        )
        self.error_string = "One or more required columns are missing or None \n"

        self.set_attributes(dict_)

        # Set required columns specific to this fault condition
        self.required_columns = [
            self.mat_col,
            self.sat_col,
            self.economizer_sig_col,
            self.cooling_sig_col,
        ]

        # Check if any of the required columns are None
        if any(col is None for col in self.required_columns):
            raise MissingColumnError(
                f"{self.error_string}"
                f"{self.equation_string}"
                f"{self.description_string}"
                f"{self.required_column_description}"
                f"{self.required_columns}"
            )

        # Ensure all required columns are strings
        self.required_columns = [str(col) for col in self.required_columns]

        self.mapped_columns = (
            f"Your config dictionary is mapped as: {', '.join(self.required_columns)}"
        )

    def get_required_columns(self) -> str:
        """Returns a string representation of the required columns."""
        return (
            f"{self.equation_string}"
            f"{self.description_string}"
            f"{self.required_column_description}"
            f"{self.mapped_columns}"
        )

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

        # Perform checks
        sat_fan_mat = abs(df[self.sat_col] - self.delta_t_supply_fan - df[self.mat_col])
        sat_mat_sqrted = np.sqrt(
            self.supply_degf_err_thres**2 + self.mix_degf_err_thres**2
        )

        combined_check = (
            (sat_fan_mat > sat_mat_sqrted)
            # Verify AHU is running in OS 3 cooling mode with minimum OA
            & (df[self.economizer_sig_col] > self.ahu_min_oa_dpr)
            & (df[self.cooling_sig_col] < 0.1)
        )

        # Rolling sum to count consecutive trues
        rolling_sum = combined_check.rolling(window=self.rolling_window_size).sum()

        # Set flag to 1 if rolling sum equals the window size
        df["fc8_flag"] = (rolling_sum >= self.rolling_window_size).astype(int)

        return df