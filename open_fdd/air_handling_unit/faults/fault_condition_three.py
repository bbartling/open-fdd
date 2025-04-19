import pandas as pd
import numpy as np
from open_fdd.core.base_fault import BaseFaultCondition
from open_fdd.core.mixins import FaultConditionMixin

class FaultConditionThree(BaseFaultCondition, FaultConditionMixin):
    """Class provides the definitions for Fault Condition 3.
    Mix temperature too high; should be between outside and return air.
    """

    def _init_specific_attributes(self, dict_):
        # Initialize specific attributes
        self.mat_col = dict_.get("MAT_COL", None)
        self.rat_col = dict_.get("RAT_COL", None)
        self.oat_col = dict_.get("OAT_COL", None)
        self.supply_vfd_speed_col = dict_.get("SUPPLY_VFD_SPEED_COL", None)
        self.mix_degf_err_thres = dict_.get("MIX_DEGF_ERR_THRES", None)
        self.outdoor_degf_err_thres = dict_.get("OUTDOOR_DEGF_ERR_THRES", None)
        self.return_degf_err_thres = dict_.get("RETURN_DEGF_ERR_THRES", None)

        # Set required columns
        self.required_columns = [
            self.mat_col,
            self.rat_col,
            self.oat_col,
            self.supply_vfd_speed_col,
        ]

        # Set documentation strings
        self.equation_string = "fc3_flag = 1 if (MAT - εMAT > max(RAT + εRAT, OAT + εOAT)) and (VFDSPD > 0) for N consecutive values else 0 \n"
        self.description_string = "Fault Condition 3: Mix temperature too high; should be between outside and return air \n"
        self.required_column_description = "Required inputs are the mixed air temperature, return air temperature, outside air temperature, and supply fan VFD speed \n"
        self.error_string = "One or more required columns are missing or None \n"

    @FaultConditionMixin._handle_errors
    def apply(self, df: pd.DataFrame) -> pd.DataFrame:
        self._apply_common_checks(df)
        self._apply_analog_checks(df, [self.supply_vfd_speed_col])

        # Specific checks
        mat_check = df[self.mat_col] - self.mix_degf_err_thres
        temp_max_check = np.maximum(
            df[self.rat_col] + self.return_degf_err_thres,
            df[self.oat_col] + self.outdoor_degf_err_thres,
        )
        combined_check = (mat_check > temp_max_check) & (
            df[self.supply_vfd_speed_col] > 0.01
        )

        self._set_fault_flag(df, combined_check, "fc3_flag")
        return df