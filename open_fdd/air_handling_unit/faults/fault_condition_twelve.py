import numpy as np
import pandas as pd

from open_fdd.core.base_fault import BaseFaultCondition
from open_fdd.core.components import FaultInputColumn, InstanceAttribute
from open_fdd.core.exceptions import InvalidParameterError
from open_fdd.core.mixins import FaultConditionMixin

INPUT_COLS = [
    FaultInputColumn(
        name="sat_col",
        constant_form="SAT_COL",
        description="Supply air temperature",
        unit="°F",
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
        name="cooling_sig_col",
        constant_form="COOLING_SIG_COL",
        description="Cooling signal",
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
]

FAULT_PARAMS = [
    InstanceAttribute(
        name="delta_t_supply_fan",
        constant_form="DELTA_T_SUPPLY_FAN",
        description="Temperature rise across supply fan",
        unit="°F",
        type=float,
    ),
    InstanceAttribute(
        name="mix_degf_err_thres",
        constant_form="MIX_DEGF_ERR_THRES",
        description="Mixed air temperature error threshold",
        unit="°F",
        type=float,
    ),
    InstanceAttribute(
        name="supply_degf_err_thres",
        constant_form="SUPPLY_DEGF_ERR_THRES",
        description="Supply air temperature error threshold",
        unit="°F",
        type=float,
    ),
    InstanceAttribute(
        name="outdoor_degf_err_thres",
        constant_form="OUTDOOR_DEGF_ERR_THRES",
        description="Outdoor air temperature error threshold",
        unit="°F",
        type=float,
    ),
    InstanceAttribute(
        name="ahu_min_oa_dpr",
        constant_form="AHU_MIN_OA_DPR",
        description="Minimum outdoor air damper position",
        unit="fraction",
        type=float,
    ),
]


class FaultConditionTwelve(BaseFaultCondition, FaultConditionMixin):
    """Class provides the definitions for Fault Condition 12.
    Supply air temperature too high; should be less than mixed air temperature
    in OS3 (economizer + mechanical cooling) and OS4 (mechanical cooling only) modes.

    py -3.12 -m pytest open_fdd/tests/ahu/test_ahu_fc12.py -rP -s
    """

    input_columns = INPUT_COLS
    fault_params = FAULT_PARAMS
    equation_string = (
        "fc12_flag = 1 if (SAT > MAT + εSAT) and "
        "((CLG > 0 and ECO > 0.9) or (CLG > 0.9 and ECO = MIN_OA)) "
        "for N consecutive values else 0 \n"
    )
    description_string = (
        "Fault Condition 12: Supply air temperature too high; should be less than "
        "mixed air temperature in OS3 (economizer + mechanical cooling) and "
        "OS4 (mechanical cooling only) modes \n"
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
        sat_col = self.get_input_column("sat_col")
        mat_col = self.get_input_column("mat_col")
        oat_col = self.get_input_column("oat_col")
        cooling_sig_col = self.get_input_column("cooling_sig_col")
        economizer_sig_col = self.get_input_column("economizer_sig_col")

        # Get parameter values using accessor methods
        delta_t_supply_fan = self.get_param("delta_t_supply_fan")
        mix_degf_err_thres = self.get_param("mix_degf_err_thres")
        supply_degf_err_thres = self.get_param("supply_degf_err_thres")
        outdoor_degf_err_thres = self.get_param("outdoor_degf_err_thres")
        ahu_min_oa_dpr = self.get_param("ahu_min_oa_dpr")

        # Check analog outputs [data with units of %] are floats only
        columns_to_check = [
            economizer_sig_col,
            cooling_sig_col,
        ]
        self._apply_analog_checks(df, columns_to_check, check_greater_than_one=True)

        # Calculate the threshold for SAT vs MAT comparison
        sat_mat_threshold = np.sqrt(supply_degf_err_thres**2 + mix_degf_err_thres**2)

        # Check if SAT is too high compared to MAT (accounting for supply fan heat)
        sat_too_high = df[sat_col] > (
            df[mat_col] + sat_mat_threshold + delta_t_supply_fan
        )

        # Check operating modes:
        # OS3: Economizer + mechanical cooling (ECO > 0.9 and CLG > 0)
        os3_mode = (df[economizer_sig_col] > 0.9) & (df[cooling_sig_col] > 0)

        # OS4: Mechanical cooling only (ECO = MIN_OA and CLG > 0.9)
        os4_mode = (df[economizer_sig_col] <= ahu_min_oa_dpr) & (
            df[cooling_sig_col] > 0.9
        )

        # Combine conditions:
        # Fault occurs when SAT is too high in either OS3 or OS4 mode
        combined_check = sat_too_high & (os3_mode | os4_mode)

        # Set fault flag
        self._set_fault_flag(df, combined_check, "fc12_flag")

        return df
