import sys

import pandas as pd

from open_fdd.core.base_fault import BaseFaultCondition
from open_fdd.core.components import FaultInputColumn, InstanceAttribute
from open_fdd.core.exceptions import InvalidParameterError
from open_fdd.core.mixins import FaultConditionMixin

INPUT_COLS = [
    FaultInputColumn(
        name="supply_fan_air_volume_col",
        constant_form="SUPPLY_FAN_AIR_VOLUME_COL",
        description="Supply fan air volume",
        unit="CFM",
        required=True,
        type=float,
    ),
    FaultInputColumn(
        name="mat_col",
        constant_form="MAT_COL",
        description="Mixed air temperature",
        unit="°F",
        required=True,
        type=float,
    ),
    FaultInputColumn(
        name="oat_col",
        constant_form="OAT_COL",
        description="Outside air temperature",
        unit="°F",
        required=True,
        type=float,
    ),
    FaultInputColumn(
        name="rat_col",
        constant_form="RAT_COL",
        description="Return air temperature",
        unit="°F",
        required=True,
        type=float,
    ),
    FaultInputColumn(
        name="supply_vfd_speed_col",
        constant_form="SUPPLY_VFD_SPEED_COL",
        description="Supply fan VFD speed",
        unit="%",
        required=True,
        type=float,
    ),
    FaultInputColumn(
        name="economizer_sig_col",
        constant_form="ECONOMIZER_SIG_COL",
        description="Economizer signal",
        unit="%",
        required=True,
        type=float,
    ),
    FaultInputColumn(
        name="heating_sig_col",
        constant_form="HEATING_SIG_COL",
        description="Heating signal",
        unit="%",
        required=True,
        type=float,
    ),
    FaultInputColumn(
        name="cooling_sig_col",
        constant_form="COOLING_SIG_COL",
        description="Cooling signal",
        unit="%",
        required=True,
        type=float,
    ),
]

FAULT_PARAMS = [
    InstanceAttribute(
        name="airflow_err_thres",
        constant_form="AIRFLOW_ERR_THRES",
        description="Airflow error threshold",
        unit="fraction",
        type=float,
        range=(0.0, 1.0),
    ),
    InstanceAttribute(
        name="ahu_min_oa_cfm_design",
        constant_form="AHU_MIN_OA_CFM_DESIGN",
        description="AHU minimum outdoor air CFM design",
        unit="CFM",
        type=float,
        range=(0.0, 100000.0),
    ),
    InstanceAttribute(
        name="outdoor_degf_err_thres",
        constant_form="OUTDOOR_DEGF_ERR_THRES",
        description="Outdoor air temperature error threshold",
        unit="°F",
        type=float,
        range=(0.0, 10.0),
    ),
    InstanceAttribute(
        name="return_degf_err_thres",
        constant_form="RETURN_DEGF_ERR_THRES",
        description="Return air temperature error threshold",
        unit="°F",
        type=float,
        range=(0.0, 10.0),
    ),
    InstanceAttribute(
        name="oat_rat_delta_min",
        constant_form="OAT_RAT_DELTA_MIN",
        description="Minimum delta between outdoor and return air temperature",
        unit="°F",
        type=float,
        range=(0.0, 20.0),
    ),
    InstanceAttribute(
        name="ahu_min_oa_dpr",
        constant_form="AHU_MIN_OA_DPR",
        description="Minimum outdoor air damper position",
        unit="fraction",
        type=float,
        range=(0.0, 1.0),
    ),
]


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

    input_columns = INPUT_COLS
    fault_params = FAULT_PARAMS
    equation_string = (
        "fc6_flag = 1 if |OA_frac_calc - OA_min| > airflow_err_thres "
        "in non-economizer modes, considering htg and mech clg OS \n"
    )
    description_string = (
        "Fault Condition 6: Issues detected with OA fraction calculation or AHU "
        "not maintaining design air flow in non-economizer conditions \n"
    )
    error_string = "One or more required columns are missing or None \n"

    def _init_specific_attributes(self, dict_):
        # Use the BaseFaultCondition's _init_specific_attributes method
        super()._init_specific_attributes(dict_)

    @FaultConditionMixin._handle_errors
    def apply(self, df: pd.DataFrame) -> pd.DataFrame:
        """Apply the fault condition to the DataFrame."""
        # Apply common checks
        self._apply_common_checks(df)

        # Get column values using accessor methods
        rat_col = self.get_input_column("rat_col")
        oat_col = self.get_input_column("oat_col")
        mat_col = self.get_input_column("mat_col")
        supply_fan_air_volume_col = self.get_input_column("supply_fan_air_volume_col")
        supply_vfd_speed_col = self.get_input_column("supply_vfd_speed_col")
        economizer_sig_col = self.get_input_column("economizer_sig_col")
        heating_sig_col = self.get_input_column("heating_sig_col")
        cooling_sig_col = self.get_input_column("cooling_sig_col")

        # Get parameter values using accessor methods
        airflow_err_thres = self.get_param("airflow_err_thres")
        ahu_min_oa_cfm_design = self.get_param("ahu_min_oa_cfm_design")
        oat_rat_delta_min = self.get_param("oat_rat_delta_min")
        ahu_min_oa_dpr = self.get_param("ahu_min_oa_dpr")

        # Check for zeros in the columns that could lead to division by zero errors
        cols_to_check = [rat_col, oat_col, supply_fan_air_volume_col]
        if df[cols_to_check].eq(0).any().any():
            print(f"Warning: Zero values found in columns: {cols_to_check}")
            print("This may cause division by zero errors.")
            sys.stdout.flush()

        # Check analog outputs [data with units of %] are floats only
        columns_to_check = [
            supply_vfd_speed_col,
            economizer_sig_col,
            heating_sig_col,
            cooling_sig_col,
        ]
        self._apply_analog_checks(df, columns_to_check, check_greater_than_one=True)

        # Calculate intermediate values
        rat_minus_oat = abs(df[rat_col] - df[oat_col])
        percent_oa_calc = (df[mat_col] - df[rat_col]) / (df[oat_col] - df[rat_col])

        # Replace negative values in percent_oa_calc with zero using vectorized operation
        percent_oa_calc = percent_oa_calc.clip(lower=0)

        perc_OAmin = ahu_min_oa_cfm_design / df[supply_fan_air_volume_col]
        percent_oa_calc_minus_perc_OAmin = abs(percent_oa_calc - perc_OAmin)

        # Combined checks for OS 1 and OS 4 modes
        os1_htg_mode_check = (
            (rat_minus_oat >= oat_rat_delta_min)
            & (percent_oa_calc_minus_perc_OAmin > airflow_err_thres)
            & (df[heating_sig_col] > 0.0)
            & (df[supply_vfd_speed_col] > 0.0)
        )

        os4_clg_mode_check = (
            (rat_minus_oat >= oat_rat_delta_min)
            & (percent_oa_calc_minus_perc_OAmin > airflow_err_thres)
            & (df[heating_sig_col] == 0.0)
            & (df[cooling_sig_col] > 0.0)
            & (df[supply_vfd_speed_col] > 0.0)
            & (df[economizer_sig_col] == ahu_min_oa_dpr)
        )

        combined_check = os1_htg_mode_check | os4_clg_mode_check

        # Set fault flag
        self._set_fault_flag(df, combined_check, "fc6_flag")

        return df
