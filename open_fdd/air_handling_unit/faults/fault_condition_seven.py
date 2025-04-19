import pandas as pd
from open_fdd.core.base_fault import BaseFaultCondition
from open_fdd.core.mixins import FaultConditionMixin
from open_fdd.core.exceptions import MissingColumnError, InvalidParameterError

class FaultConditionSeven(BaseFaultCondition, FaultConditionMixin):
    """Class provides the definitions for Fault Condition 7.
    Very similar to FC 13 but uses heating valve.
    Supply air temperature too low in full heating.

    py -3.12 -m pytest open_fdd/tests/ahu/test_ahu_fc7.py -rP -s
    """

    def _init_specific_attributes(self, dict_):
        # Threshold parameters
        self.supply_degf_err_thres = dict_.get("SUPPLY_DEGF_ERR_THRES", None)

        # Validate that threshold parameters are floats
        if not isinstance(self.supply_degf_err_thres, float):
            raise InvalidParameterError(
                f"The parameter 'supply_degf_err_thres' should be a float, but got {type(self.supply_degf_err_thres).__name__}."
            )

        # Other attributes
        self.sat_col = dict_.get("SAT_COL", None)
        self.sat_setpoint_col = dict_.get("SAT_SETPOINT_COL", None)
        self.heating_sig_col = dict_.get("HEATING_SIG_COL", None)
        self.supply_vfd_speed_col = dict_.get("SUPPLY_VFD_SPEED_COL", None)

        # Set documentation strings
        self.equation_string = (
            "fc7_flag = 1 if SAT < (SATSP - εSAT) in full heating mode "
            "and VFD speed > 0 for N consecutive values else 0 \n"
        )
        self.description_string = (
            "Fault Condition 7: Supply air temperature too low in full heating mode "
            "with heating valve fully open \n"
        )
        self.required_column_description = (
            "Required inputs are the supply air temperature, supply air temperature setpoint, "
            "heating signal, and supply fan VFD speed \n"
        )
        self.error_string = "One or more required columns are missing or None \n"

        # Set required columns specific to this fault condition
        self.required_columns = [
            self.sat_col,
            self.sat_setpoint_col,
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
        sat_check = df[self.sat_setpoint_col] - self.supply_degf_err_thres

        combined_check = (
            (df[self.sat_col] < sat_check)
            & (df[self.heating_sig_col] > 0.9)
            & (df[self.supply_vfd_speed_col] > 0)
        )

        # Set fault flag
        self._set_fault_flag(df, combined_check, "fc7_flag")

        return df
