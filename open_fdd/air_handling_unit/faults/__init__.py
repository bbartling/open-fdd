import pandas as pd
import numpy as np
from open_fdd.core.base_fault import BaseFaultCondition
from open_fdd.core.mixins import FaultConditionMixin
from open_fdd.air_handling_unit.faults.helper_utils import SharedUtils
import operator
import sys
from open_fdd.core.exceptions import MissingColumnError, InvalidParameterError


class FaultConditionOne(BaseFaultCondition, FaultConditionMixin):
    """Class provides the definitions for Fault Condition 1.
    AHU low duct static pressure fan fault.

    py -3.12 -m pytest open_fdd/tests/ahu/test_ahu_fc1.py -rP -s
    """

    def _init_specific_attributes(self, dict_):
        # Initialize specific attributes
        self.duct_static_col = dict_.get("DUCT_STATIC_COL", None)
        self.supply_vfd_speed_col = dict_.get("SUPPLY_VFD_SPEED_COL", None)
        self.duct_static_setpoint_col = dict_.get("DUCT_STATIC_SETPOINT_COL", None)
        self.duct_static_inches_err_thres = dict_.get(
            "DUCT_STATIC_INCHES_ERR_THRES", None
        )
        self.vfd_speed_percent_max = dict_.get("VFD_SPEED_PERCENT_MAX", None)
        self.vfd_speed_percent_err_thres = dict_.get(
            "VFD_SPEED_PERCENT_ERR_THRES", None
        )

        # Set required columns
        self.required_columns = [
            self.duct_static_col,
            self.supply_vfd_speed_col,
            self.duct_static_setpoint_col,
        ]

        # Set documentation strings
        self.equation_string = "fc1_flag = 1 if (DP < DPSP - εDP) and (VFDSPD >= VFDSPD_max - εVFDSPD) for N consecutive values else 0 \n"
        self.description_string = (
            "Fault Condition 1: Duct static too low at fan at full speed \n"
        )
        self.required_column_description = "Required inputs are the duct static pressure, setpoint, and supply fan VFD speed \n"
        self.error_string = "One or more required columns are missing or None \n"

    @FaultConditionMixin._handle_errors
    def apply(self, df: pd.DataFrame) -> pd.DataFrame:
        self._apply_common_checks(df)
        self._apply_analog_checks(df, [self.supply_vfd_speed_col])

        # Convert VFD speed from percentage to fraction if needed
        if (df[self.supply_vfd_speed_col] > 1.0).any():
            df[self.supply_vfd_speed_col] = df[self.supply_vfd_speed_col] / 100.0

        # Convert thresholds from percentage to fraction
        vfd_speed_max = self.vfd_speed_percent_max / 100.0
        vfd_speed_err_thres = self.vfd_speed_percent_err_thres / 100.0

        # Specific checks
        static_check = (
            df[self.duct_static_col]
            < df[self.duct_static_setpoint_col] - self.duct_static_inches_err_thres
        )
        fan_check = df[self.supply_vfd_speed_col] >= vfd_speed_max - vfd_speed_err_thres
        combined_check = static_check & fan_check

        self._set_fault_flag(df, combined_check, "fc1_flag")
        return df


class FaultConditionTwo(BaseFaultCondition, FaultConditionMixin):
    """Class provides the definitions for Fault Condition 2.
    Mix temperature too low; should be between outside and return air.
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
        self.equation_string = "fc2_flag = 1 if (MAT - εMAT < min(RAT - εRAT, OAT - εOAT)) and (VFDSPD > 0) for N consecutive values else 0 \n"
        self.description_string = "Fault Condition 2: Mix temperature too low; should be between outside and return air \n"
        self.required_column_description = "Required inputs are the mixed air temperature, return air temperature, outside air temperature, and supply fan VFD speed \n"
        self.error_string = "One or more required columns are missing or None \n"

    @FaultConditionMixin._handle_errors
    def apply(self, df: pd.DataFrame) -> pd.DataFrame:
        self._apply_common_checks(df)
        self._apply_analog_checks(df, [self.supply_vfd_speed_col])

        # Specific checks
        mat_check = df[self.mat_col] - self.mix_degf_err_thres
        temp_min_check = np.minimum(
            df[self.rat_col] - self.return_degf_err_thres,
            df[self.oat_col] - self.outdoor_degf_err_thres,
        )
        combined_check = (mat_check < temp_min_check) & (
            df[self.supply_vfd_speed_col] > 0.01
        )

        self._set_fault_flag(df, combined_check, "fc2_flag")
        return df


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


class FaultConditionTen(BaseFaultCondition, FaultConditionMixin):
    """Class provides the definitions for Fault Condition 10.
    Outdoor air temperature and mix air temperature should
    be approx equal in economizer plus mech cooling mode.

    py -3.12 -m pytest open_fdd/tests/ahu/test_ahu_fc10.py -rP -s
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
        self.cooling_sig_col = dict_.get("COOLING_SIG_COL", None)
        self.economizer_sig_col = dict_.get("ECONOMIZER_SIG_COL", None)

        # Set documentation strings
        self.equation_string = (
            "fc10_flag = 1 if |OAT - MAT| > √(εOAT² + εMAT²) in "
            "economizer + mech cooling mode for N consecutive values else 0 \n"
        )
        self.description_string = (
            "Fault Condition 10: Outdoor air temperature and mixed air temperature "
            "should be approximately equal in economizer plus mechanical cooling mode \n"
        )
        self.required_column_description = (
            "Required inputs are the outside air temperature, mixed air temperature, "
            "cooling signal, and economizer signal \n"
        )
        self.error_string = "One or more required columns are missing or None \n"

        # Set required columns specific to this fault condition
        self.required_columns = [
            self.oat_col,
            self.mat_col,
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
        abs_mat_minus_oat = abs(df[self.mat_col] - df[self.oat_col])
        mat_oat_sqrted = np.sqrt(
            self.mix_degf_err_thres**2 + self.outdoor_degf_err_thres**2
        )

        combined_check = (
            (abs_mat_minus_oat > mat_oat_sqrted)
            # Verify AHU is running in OS 3 cooling mode with minimum OA
            & (df[self.cooling_sig_col] > 0.01)
            & (df[self.economizer_sig_col] > 0.9)
        )

        # Set fault flag
        self._set_fault_flag(df, combined_check, "fc10_flag")

        return df


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


class FaultConditionFourteen(BaseFaultCondition, FaultConditionMixin):
    """Class provides the definitions for Fault Condition 14.
    Temperature drop across inactive cooling coil in OS1 (heating) and OS2 (economizer) modes.
    This fault checks if there is an unexpected temperature drop across the cooling coil
    when it should be inactive.

    py -3.12 -m pytest open_fdd/tests/ahu/test_ahu_fc14.py -rP -s
    """

    def _init_specific_attributes(self, dict_):
        # Threshold parameters
        self.delta_t_supply_fan = dict_.get("DELTA_T_SUPPLY_FAN", None)
        self.coil_temp_enter_err_thres = dict_.get("COIL_TEMP_ENTER_ERR_THRES", None)
        self.coil_temp_leave_err_thres = dict_.get("COIL_TEMP_LEAV_ERR_THRES", None)
        self.ahu_min_oa_dpr = dict_.get("AHU_MIN_OA_DPR", None)

        # Validate that threshold parameters are floats
        for param, value in [
            ("delta_t_supply_fan", self.delta_t_supply_fan),
            ("coil_temp_enter_err_thres", self.coil_temp_enter_err_thres),
            ("coil_temp_leave_err_thres", self.coil_temp_leave_err_thres),
            ("ahu_min_oa_dpr", self.ahu_min_oa_dpr),
        ]:
            if not isinstance(value, float):
                raise InvalidParameterError(
                    f"The parameter '{param}' should be a float, but got {type(value).__name__}."
                )

        # Other attributes
        self.clg_coil_enter_temp_col = dict_.get("CLG_COIL_ENTER_TEMP_COL", None)
        self.clg_coil_leave_temp_col = dict_.get("CLG_COIL_LEAVE_TEMP_COL", None)
        self.cooling_sig_col = dict_.get("COOLING_SIG_COL", None)
        self.heating_sig_col = dict_.get("HEATING_SIG_COL", None)
        self.economizer_sig_col = dict_.get("ECONOMIZER_SIG_COL", None)
        self.supply_vfd_speed_col = dict_.get("SUPPLY_VFD_SPEED_COL", None)

        # Set documentation strings
        self.equation_string = (
            "fc14_flag = 1 if (CLG_LEAVE < CLG_ENTER - √(εENTER² + εLEAVE²)) "
            "in OS1 (heating) or OS2 (economizer) modes for N consecutive values else 0 \n"
        )
        self.description_string = (
            "Fault Condition 14: Temperature drop across inactive cooling coil "
            "in OS1 (heating) and OS2 (economizer) modes \n"
        )
        self.required_column_description = (
            "Required inputs are the cooling coil entering and leaving air temperatures, "
            "cooling signal, heating signal, economizer signal, and supply fan VFD speed \n"
        )
        self.error_string = "One or more required columns are missing or None \n"

        # Set required columns specific to this fault condition
        self.required_columns = [
            self.clg_coil_enter_temp_col,
            self.clg_coil_leave_temp_col,
            self.cooling_sig_col,
            self.heating_sig_col,
            self.economizer_sig_col,
            self.supply_vfd_speed_col,
        ]

    @FaultConditionMixin._handle_errors
    def apply(self, df: pd.DataFrame) -> pd.DataFrame:
        """Apply the fault condition to the DataFrame."""
        # Apply common checks
        self._apply_common_checks(df)

        # Check analog outputs [data with units of %] are floats only
        columns_to_check = [
            self.cooling_sig_col,
            self.heating_sig_col,
            self.economizer_sig_col,
            self.supply_vfd_speed_col,
        ]
        self._apply_analog_checks(df, columns_to_check)

        # Calculate the threshold for temperature drop
        temp_drop_threshold = np.sqrt(
            self.coil_temp_enter_err_thres**2 + self.coil_temp_leave_err_thres**2
        )

        # Check if there's a significant temperature drop across the cooling coil
        temp_drop = df[self.clg_coil_enter_temp_col] - df[self.clg_coil_leave_temp_col]
        significant_temp_drop = temp_drop > temp_drop_threshold

        # Check operating modes:
        # OS1: Heating mode (HTG > 0, CLG = 0, ECO = MIN_OA)
        os1_mode = (
            (df[self.heating_sig_col] > 0.0)
            & (df[self.cooling_sig_col] == 0.0)
            & (df[self.economizer_sig_col] <= self.ahu_min_oa_dpr)
        )

        # OS2: Economizer mode (HTG = 0, CLG = 0, ECO > MIN_OA)
        os2_mode = (
            (df[self.heating_sig_col] == 0.0)
            & (df[self.cooling_sig_col] == 0.0)
            & (df[self.economizer_sig_col] > self.ahu_min_oa_dpr)
        )

        # Combine conditions:
        # Fault occurs when there's a significant temperature drop across an inactive cooling coil
        # in either OS1 (heating) or OS2 (economizer) mode
        combined_check = significant_temp_drop & (os1_mode | os2_mode)

        # Set fault flag
        self._set_fault_flag(df, combined_check, "fc14_flag")

        return df


class FaultConditionFifteen(BaseFaultCondition, FaultConditionMixin):
    """Class provides the definitions for Fault Condition 15.
    Temperature rise across inactive heating coil in OS2 (economizer),
    OS3 (economizer + mechanical cooling), and OS4 (mechanical cooling only) modes.
    This fault checks if there is an unexpected temperature rise across the heating coil
    when it should be inactive.

    py -3.12 -m pytest open_fdd/tests/ahu/test_ahu_fc15.py -rP -s
    """

    def _init_specific_attributes(self, dict_):
        # Threshold parameters
        self.delta_t_supply_fan = dict_.get("DELTA_SUPPLY_FAN", None)
        self.coil_temp_enter_err_thres = dict_.get("COIL_TEMP_ENTER_ERR_THRES", None)
        self.coil_temp_leave_err_thres = dict_.get("COIL_TEMP_LEAV_ERR_THRES", None)
        self.ahu_min_oa_dpr = dict_.get("AHU_MIN_OA_DPR", None)

        # Validate that threshold parameters are floats
        for param, value in [
            ("delta_t_supply_fan", self.delta_t_supply_fan),
            ("coil_temp_enter_err_thres", self.coil_temp_enter_err_thres),
            ("coil_temp_leave_err_thres", self.coil_temp_leave_err_thres),
            ("ahu_min_oa_dpr", self.ahu_min_oa_dpr),
        ]:
            if not isinstance(value, float):
                raise InvalidParameterError(
                    f"The parameter '{param}' should be a float, but got {type(value).__name__}."
                )

        # Other attributes
        self.htg_coil_enter_temp_col = dict_.get("HTG_COIL_ENTER_TEMP_COL", None)
        self.htg_coil_leave_temp_col = dict_.get("HTG_COIL_LEAVE_TEMP_COL", None)
        self.cooling_sig_col = dict_.get("COOLING_SIG_COL", None)
        self.heating_sig_col = dict_.get("HEATING_SIG_COL", None)
        self.economizer_sig_col = dict_.get("ECONOMIZER_SIG_COL", None)
        self.supply_vfd_speed_col = dict_.get("SUPPLY_VFD_SPEED_COL", None)

        # Set documentation strings
        self.equation_string = (
            "fc15_flag = 1 if (HTG_LEAVE > HTG_ENTER + √(εENTER² + εLEAVE²) + ΔTfan) "
            "in OS2 (economizer), OS3 (economizer + mechanical cooling), or "
            "OS4 (mechanical cooling only) modes for N consecutive values else 0 \n"
        )
        self.description_string = (
            "Fault Condition 15: Temperature rise across inactive heating coil "
            "in OS2 (economizer), OS3 (economizer + mechanical cooling), and "
            "OS4 (mechanical cooling only) modes \n"
        )
        self.required_column_description = (
            "Required inputs are the heating coil entering and leaving air temperatures, "
            "cooling signal, heating signal, economizer signal, and supply fan VFD speed \n"
        )
        self.error_string = "One or more required columns are missing or None \n"

        # Set required columns specific to this fault condition
        self.required_columns = [
            self.htg_coil_enter_temp_col,
            self.htg_coil_leave_temp_col,
            self.cooling_sig_col,
            self.heating_sig_col,
            self.economizer_sig_col,
            self.supply_vfd_speed_col,
        ]

    @FaultConditionMixin._handle_errors
    def apply(self, df: pd.DataFrame) -> pd.DataFrame:
        """Apply the fault condition to the DataFrame."""
        # Apply common checks
        self._apply_common_checks(df)

        # Check analog outputs [data with units of %] are floats only
        columns_to_check = [
            self.cooling_sig_col,
            self.heating_sig_col,
            self.economizer_sig_col,
            self.supply_vfd_speed_col,
        ]
        self._apply_analog_checks(df, columns_to_check)

        # Calculate the threshold for temperature rise, including supply fan heat
        temp_rise_threshold = (
            np.sqrt(
                self.coil_temp_enter_err_thres**2 + self.coil_temp_leave_err_thres**2
            )
            + self.delta_t_supply_fan
        )

        # Check if there's a significant temperature rise across the heating coil
        temp_rise = df[self.htg_coil_leave_temp_col] - df[self.htg_coil_enter_temp_col]
        significant_temp_rise = temp_rise > temp_rise_threshold

        # Check operating modes:
        # OS2: Economizer mode (HTG = 0, CLG = 0, ECO > MIN_OA)
        os2_mode = (
            (df[self.heating_sig_col] == 0.0)
            & (df[self.cooling_sig_col] == 0.0)
            & (df[self.economizer_sig_col] > self.ahu_min_oa_dpr)
        )

        # OS3: Economizer + mechanical cooling (HTG = 0, CLG > 0, ECO > 0.9)
        os3_mode = (
            (df[self.heating_sig_col] == 0.0)
            & (df[self.cooling_sig_col] > 0.0)
            & (df[self.economizer_sig_col] > 0.9)
        )

        # OS4: Mechanical cooling only (HTG = 0, CLG > 0, ECO = MIN_OA)
        os4_mode = (
            (df[self.heating_sig_col] == 0.0)
            & (df[self.cooling_sig_col] > 0.0)
            & (df[self.economizer_sig_col] <= self.ahu_min_oa_dpr)
        )

        # Combine conditions:
        # Fault occurs when there's a significant temperature rise across an inactive heating coil
        # in OS2 (economizer), OS3 (economizer + mechanical cooling), or OS4 (mechanical cooling only) mode
        combined_check = significant_temp_rise & (os2_mode | os3_mode | os4_mode)

        # Set fault flag
        self._set_fault_flag(df, combined_check, "fc15_flag")

        return df


class FaultConditionSixteen(BaseFaultCondition, FaultConditionMixin):
    """Class provides the definitions for Fault Condition 16.
    ERV effectiveness should be within specified thresholds based on OAT.
    This fault checks if the ERV (Energy Recovery Ventilator) is operating
    within expected efficiency ranges in both heating and cooling modes.

    py -3.12 -m pytest open_fdd/tests/ahu/test_ahu_fc16.py -rP -s
    """

    def _init_specific_attributes(self, dict_):
        # Threshold parameters
        self.erv_efficiency_min_heating = dict_.get("ERV_EFFICIENCY_MIN_HEATING", None)
        self.erv_efficiency_max_heating = dict_.get("ERV_EFFICIENCY_MAX_HEATING", None)
        self.erv_efficiency_min_cooling = dict_.get("ERV_EFFICIENCY_MIN_COOLING", None)
        self.erv_efficiency_max_cooling = dict_.get("ERV_EFFICIENCY_MAX_COOLING", None)
        self.oat_low_threshold = dict_.get("OAT_LOW_THRESHOLD", None)
        self.oat_high_threshold = dict_.get("OAT_HIGH_THRESHOLD", None)
        self.oat_rat_delta_min = dict_.get("OAT_RAT_DELTA_MIN", None)

        # Validate that threshold parameters are floats
        for param, value in [
            ("erv_efficiency_min_heating", self.erv_efficiency_min_heating),
            ("erv_efficiency_max_heating", self.erv_efficiency_max_heating),
            ("erv_efficiency_min_cooling", self.erv_efficiency_min_cooling),
            ("erv_efficiency_max_cooling", self.erv_efficiency_max_cooling),
            ("oat_low_threshold", self.oat_low_threshold),
            ("oat_high_threshold", self.oat_high_threshold),
            ("oat_rat_delta_min", self.oat_rat_delta_min),
        ]:
            if not isinstance(value, float):
                raise InvalidParameterError(
                    f"The parameter '{param}' should be a float, but got {type(value).__name__}."
                )

        # Validate that efficiency values are between 0.0 and 1.0
        for param, value in [
            ("ERV_EFFICIENCY_MIN_HEATING", self.erv_efficiency_min_heating),
            ("ERV_EFFICIENCY_MAX_HEATING", self.erv_efficiency_max_heating),
            ("ERV_EFFICIENCY_MIN_COOLING", self.erv_efficiency_min_cooling),
            ("ERV_EFFICIENCY_MAX_COOLING", self.erv_efficiency_max_cooling),
        ]:
            if not 0.0 <= value <= 1.0:
                raise InvalidParameterError(
                    f"The parameter '{param}' should be a float between 0.0 and 1.0, but got {value}."
                )

        # Other attributes
        self.erv_oat_enter_col = dict_.get("ERV_OAT_ENTER_COL", None)
        self.erv_oat_leaving_col = dict_.get("ERV_OAT_LEAVING_COL", None)
        self.erv_eat_enter_col = dict_.get("ERV_EAT_ENTER_COL", None)
        self.erv_eat_leaving_col = dict_.get("ERV_EAT_LEAVING_COL", None)
        self.supply_vfd_speed_col = dict_.get("SUPPLY_VFD_SPEED_COL", None)

        # Set documentation strings
        self.equation_string = (
            "fc16_flag = 1 if ERV effectiveness is outside expected range "
            "(heating: εmin_htg ≤ ε ≤ εmax_htg, cooling: εmin_clg ≤ ε ≤ εmax_clg) "
            "for N consecutive values else 0 \n"
        )
        self.description_string = (
            "Fault Condition 16: ERV effectiveness should be within specified "
            "thresholds based on OAT \n"
        )
        self.required_column_description = (
            "Required inputs are the ERV outdoor air entering and leaving temperatures, "
            "ERV exhaust air entering and leaving temperatures, and supply fan VFD speed \n"
        )
        self.error_string = "One or more required columns are missing or None \n"

        # Set required columns specific to this fault condition
        self.required_columns = [
            self.erv_oat_enter_col,
            self.erv_oat_leaving_col,
            self.erv_eat_enter_col,
            self.erv_eat_leaving_col,
            self.supply_vfd_speed_col,
        ]

    @FaultConditionMixin._handle_errors
    def apply(self, df: pd.DataFrame) -> pd.DataFrame:
        """Apply the fault condition to the DataFrame."""
        # Apply common checks
        self._apply_common_checks(df)

        # Check analog outputs [data with units of %] are floats only
        columns_to_check = [self.supply_vfd_speed_col]
        self._apply_analog_checks(df, columns_to_check)

        # Calculate temperature differences
        oat_rat_delta = abs(df[self.erv_oat_enter_col] - df[self.erv_eat_enter_col])

        # Calculate ERV effectiveness
        # ε = (T_leaving - T_entering) / (T_exhaust - T_entering)
        erv_effectiveness = (
            df[self.erv_oat_leaving_col] - df[self.erv_oat_enter_col]
        ) / (df[self.erv_eat_enter_col] - df[self.erv_oat_enter_col])

        # Determine operating mode based on OAT
        heating_mode = df[self.erv_oat_enter_col] < self.oat_low_threshold
        cooling_mode = df[self.erv_oat_enter_col] > self.oat_high_threshold

        # Check effectiveness against thresholds
        low_effectiveness_htg = heating_mode & (
            erv_effectiveness < self.erv_efficiency_min_heating
        )
        high_effectiveness_htg = heating_mode & (
            erv_effectiveness > self.erv_efficiency_max_heating
        )
        low_effectiveness_clg = cooling_mode & (
            erv_effectiveness < self.erv_efficiency_min_cooling
        )
        high_effectiveness_clg = cooling_mode & (
            erv_effectiveness > self.erv_efficiency_max_cooling
        )

        # Combine conditions:
        # Fault occurs when ERV effectiveness is outside expected range
        # and there's sufficient temperature difference between OAT and RAT
        combined_check = (oat_rat_delta >= self.oat_rat_delta_min) & (
            low_effectiveness_htg
            | high_effectiveness_htg
            | low_effectiveness_clg
            | high_effectiveness_clg
        )

        # Set fault flag
        self._set_fault_flag(df, combined_check, "fc16_flag")

        return df
