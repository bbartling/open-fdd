import pandas as pd
import sys
from open_fdd.core.base_fault import BaseFaultCondition
from open_fdd.core.mixins import FaultConditionMixin
from open_fdd.core.exceptions import InvalidParameterError

class FaultConditionSix(BaseFaultCondition, FaultConditionMixin):
    """Class provides the definitions for Fault Condition 6.

    This fault related to knowing the design air flow for
    ventilation AHU_MIN_CFM_DESIGN which comes from the
    design mech engineered records where then the fault
    tries to calculate that based on totalized measured
    AHU air flow and outside air fraction calc from
    AHU temp sensors. The fault could flag issues where
    flow stations are either not in calibration, temp
    sensors used in the OA frac calc, or possibly the AHU
    not bringing in design air flow when not operating in
    economizer free cooling modes.

    py -3.12 -m pytest open_fdd/tests/ahu/test_ahu_fc6.py -rP -s
    """

    def _init_specific_attributes(self, dict_):
        # Threshold parameters
        self.airflow_err_thres = dict_.get("AIRFLOW_ERR_THRES", None)
        self.ahu_min_oa_cfm_design = dict_.get("AHU_MIN_OA_CFM_DESIGN", None)
        self.outdoor_degf_err_thres = dict_.get("OUTDOOR_DEGF_ERR_THRES", None)
        self.return_degf_err_thres = dict_.get("RETURN_DEGF_ERR_THRES", None)
        self.oat_rat_delta_min = dict_.get("OAT_RAT_DELTA_MIN", None)
        self.ahu_min_oa_dpr = dict_.get("AHU_MIN_OA_DPR", None)

        if not isinstance(self.ahu_min_oa_cfm_design, (float, int)):
            raise InvalidParameterError(
                f"The parameter 'ahu_min_oa_cfm_design' should be an integer data type, but got {type(self.ahu_min_oa_cfm_design).__name__}."
            )

        # Validate that threshold parameters are floats
        for param, value in [
            ("airflow_err_thres", self.airflow_err_thres),
            ("outdoor_degf_err_thres", self.outdoor_degf_err_thres),
            ("return_degf_err_thres", self.return_degf_err_thres),
            ("oat_rat_delta_min", self.oat_rat_delta_min),
            ("ahu_min_oa_dpr", self.ahu_min_oa_dpr),
        ]:
            if not isinstance(value, float):
                raise InvalidParameterError(
                    f"The parameter '{param}' should be a float, but got {type(value).__name__}."
                )

        # Other attributes
        self.supply_fan_air_volume_col = dict_.get("SUPPLY_FAN_AIR_VOLUME_COL", None)
        self.mat_col = dict_.get("MAT_COL", None)
        self.oat_col = dict_.get("OAT_COL", None)
        self.rat_col = dict_.get("RAT_COL", None)
        self.supply_vfd_speed_col = dict_.get("SUPPLY_VFD_SPEED_COL", None)
        self.economizer_sig_col = dict_.get("ECONOMIZER_SIG_COL", None)
        self.heating_sig_col = dict_.get("HEATING_SIG_COL", None)
        self.cooling_sig_col = dict_.get("COOLING_SIG_COL", None)

        # Set documentation strings
        self.equation_string = (
            "fc6_flag = 1 if |OA_frac_calc - OA_min| > airflow_err_thres "
            "in non-economizer modes, considering htg and mech clg OS \n"
        )
        self.description_string = (
            "Fault Condition 6: Issues detected with OA fraction calculation or AHU "
            "not maintaining design air flow in non-economizer conditions \n"
        )
        self.required_column_description = (
            "Required inputs are the supply fan air volume, mixed air temperature, "
            "outside air temperature, return air temperature, and VFD speed. "
            "Optional inputs include economizer signal, heating signal, and cooling signal \n"
        )
        self.error_string = "One or more required columns are missing or None \n"

        # Set required columns specific to this fault condition
        self.required_columns = [
            self.supply_fan_air_volume_col,
            self.mat_col,
            self.oat_col,
            self.rat_col,
            self.supply_vfd_speed_col,
            self.economizer_sig_col,
            self.heating_sig_col,
            self.cooling_sig_col,
        ]

    @FaultConditionMixin._handle_errors
    def apply(self, df: pd.DataFrame) -> pd.DataFrame:
        """Apply the fault condition to the DataFrame."""
        # Apply common checks
        self._apply_common_checks(df)

        # Check for zeros in the columns that could lead to division by zero errors
        cols_to_check = [self.rat_col, self.oat_col, self.supply_fan_air_volume_col]
        if df[cols_to_check].eq(0).any().any():
            print(f"Warning: Zero values found in columns: {cols_to_check}")
            print("This may cause division by zero errors.")
            sys.stdout.flush()

        # Check analog outputs [data with units of %] are floats only
        columns_to_check = [
            self.supply_vfd_speed_col,
            self.economizer_sig_col,
            self.heating_sig_col,
            self.cooling_sig_col,
        ]
        self._apply_analog_checks(df, columns_to_check)

        # Calculate intermediate values
        rat_minus_oat = abs(df[self.rat_col] - df[self.oat_col])
        percent_oa_calc = (df[self.mat_col] - df[self.rat_col]) / (
            df[self.oat_col] - df[self.rat_col]
        )

        # Replace negative values in percent_oa_calc with zero using vectorized operation
        percent_oa_calc = percent_oa_calc.clip(lower=0)

        perc_OAmin = self.ahu_min_oa_cfm_design / df[self.supply_fan_air_volume_col]
        percent_oa_calc_minus_perc_OAmin = abs(percent_oa_calc - perc_OAmin)

        # Combined checks for OS 1 and OS 4 modes
        os1_htg_mode_check = (
            (rat_minus_oat >= self.oat_rat_delta_min)
            & (percent_oa_calc_minus_perc_OAmin > self.airflow_err_thres)
            & (df[self.heating_sig_col] > 0.0)
            & (df[self.supply_vfd_speed_col] > 0.0)
        )

        os4_clg_mode_check = (
            (rat_minus_oat >= self.oat_rat_delta_min)
            & (percent_oa_calc_minus_perc_OAmin > self.airflow_err_thres)
            & (df[self.heating_sig_col] == 0.0)
            & (df[self.cooling_sig_col] > 0.0)
            & (df[self.supply_vfd_speed_col] > 0.0)
            & (df[self.economizer_sig_col] == self.ahu_min_oa_dpr)
        )

        combined_check = os1_htg_mode_check | os4_clg_mode_check

        # Set fault flag
        self._set_fault_flag(df, combined_check, "fc6_flag")

        return df