import pandas as pd
from open_fdd.core.base_fault import BaseFaultCondition
from open_fdd.core.mixins import FaultConditionMixin
from open_fdd.core.exceptions import MissingColumnError, InvalidParameterError

class FaultConditionFour(BaseFaultCondition, FaultConditionMixin):
    """Class provides the definitions for Fault Condition 4.

    This fault flags excessive operating states on the AHU
    if it's hunting between heating, econ, econ+mech, and
    a mech clg modes. The code counts how many operating
    changes in an hour and will throw a fault if there is
    excessive OS changes to flag control sys hunting.

    py -3.12 -m pytest open_fdd/tests/ahu/test_ahu_fc4.py -rP -s
    """

    def _init_specific_attributes(self, dict_):
        # Threshold parameters
        self.delta_os_max = dict_.get("DELTA_OS_MAX", None)
        self.ahu_min_oa_dpr = dict_.get("AHU_MIN_OA_DPR", None)

        # Validate that delta_os_max can be either a float or an integer
        if not isinstance(self.delta_os_max, (int)):
            raise InvalidParameterError(
                f"The parameter 'delta_os_max' should be an integer data type, but got {type(self.delta_os_max).__name__}."
            )

        # Validate that ahu_min_oa_dpr is a float
        if not isinstance(self.ahu_min_oa_dpr, float):
            raise InvalidParameterError(
                f"The parameter 'ahu_min_oa_dpr' should be a float, but got {type(self.ahu_min_oa_dpr).__name__}."
            )

        # Other attributes
        self.economizer_sig_col = dict_.get("ECONOMIZER_SIG_COL", None)
        self.heating_sig_col = dict_.get("HEATING_SIG_COL", None)
        self.cooling_sig_col = dict_.get("COOLING_SIG_COL", None)
        self.supply_vfd_speed_col = dict_.get("SUPPLY_VFD_SPEED_COL", None)

        # Set documentation strings
        self.equation_string = (
            "fc4_flag = 1 if excessive mode changes (> δOS_max) occur "
            "within an hour across heating, econ, econ+mech, mech clg, and min OA modes \n"
        )
        self.description_string = "Fault Condition 4: Excessive AHU operating state changes detected (hunting behavior) \n"
        self.required_column_description = (
            "Required inputs are the economizer signal, supply fan VFD speed, "
            "and optionally heating and cooling signals \n"
        )
        self.error_string = "One or more required columns are missing or None \n"

        # Set required columns, making heating and cooling optional
        self.required_columns = [
            self.economizer_sig_col,
            self.supply_vfd_speed_col,
        ]

        # If heating or cooling columns are provided, add them to the required columns
        if self.heating_sig_col:
            self.required_columns.append(self.heating_sig_col)
        if self.cooling_sig_col:
            self.required_columns.append(self.cooling_sig_col)

    @FaultConditionMixin._handle_errors
    def apply(self, df: pd.DataFrame) -> pd.DataFrame:
        """Apply the fault condition to the DataFrame."""
        # Apply common checks
        self._apply_common_checks(df)
        # Add analog checks for supply_vfd_speed_col
        self._apply_analog_checks(df, [self.supply_vfd_speed_col])

        # Convert VFD speed from percentage to fraction if needed
        if (df[self.supply_vfd_speed_col] > 1.0).any():
            df[self.supply_vfd_speed_col] = df[self.supply_vfd_speed_col] / 100.0

        # Calculate operating state changes
        df["os_change"] = 0
        df.loc[df[self.economizer_sig_col] > 0, "os_change"] += 1
        df.loc[df[self.supply_vfd_speed_col] > self.ahu_min_oa_dpr, "os_change"] += 1
        if self.heating_sig_col:
            df.loc[df[self.heating_sig_col] > 0, "os_change"] += 1
        if self.cooling_sig_col:
            df.loc[df[self.cooling_sig_col] > 0, "os_change"] += 1

        # Calculate changes in operating state
        df["os_change_diff"] = df["os_change"].diff().abs()
        df["os_change_diff"] = df["os_change_diff"].fillna(0)

        # Calculate rolling sum of changes
        df["os_change_sum"] = df["os_change_diff"].rolling(window=60).sum()

        # Set fault flag
        df["fc4_flag"] = (df["os_change_sum"] > self.delta_os_max).astype(int)

        return df