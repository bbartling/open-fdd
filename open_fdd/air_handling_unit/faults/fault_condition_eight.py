import numpy as np
import pandas as pd

from open_fdd.core.base_fault import BaseFaultCondition
from open_fdd.core.components import FaultInputColumn, InstanceAttribute
from open_fdd.core.exceptions import InvalidParameterError, MissingColumnError
from open_fdd.core.mixins import FaultConditionMixin

INPUT_COLS = [
    FaultInputColumn(
        name="mat_col",
        constant_form="MAT_COL",
        description="Mixed air temperature",
        unit="°F",
        required=True,
        type=float,
    ),
    FaultInputColumn(
        name="sat_col",
        constant_form="SAT_COL",
        description="Supply air temperature",
        unit="°F",
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
        name="ahu_min_oa_dpr",
        constant_form="AHU_MIN_OA_DPR",
        description="Minimum outdoor air damper position",
        unit="fraction",
        type=float,
    ),
]


class FaultConditionEight(BaseFaultCondition, FaultConditionMixin):
    """Class provides the definitions for Fault Condition 8.
    Supply air temperature and mix air temperature should
    be approx equal in economizer mode.

    py -3.12 -m pytest open_fdd/tests/ahu/test_ahu_fc8.py -rP -s
    """

    input_columns = INPUT_COLS
    fault_params = FAULT_PARAMS
    equation_string = (
        "fc8_flag = 1 if |SAT - MAT - ΔT_fan| > √(εSAT² + εMAT²) "
        "in economizer mode for N consecutive values else 0 \n"
    )
    description_string = (
        "Fault Condition 8: Supply air temperature and mixed air temperature should "
        "be approximately equal in economizer mode \n"
    )
    error_string = "One or more required columns are missing or None \n"

    @FaultConditionMixin._handle_errors
    def apply(self, df: pd.DataFrame) -> pd.DataFrame:
        """Apply the fault condition to the DataFrame."""
        # Apply common checks
        self._apply_common_checks(df)

        # Get column values using accessor methods
        mat_col = self.get_input_column("mat_col")
        sat_col = self.get_input_column("sat_col")
        economizer_sig_col = self.get_input_column("economizer_sig_col")
        cooling_sig_col = self.get_input_column("cooling_sig_col")

        # Get parameter values using accessor methods
        delta_t_supply_fan = self.get_param("delta_t_supply_fan")
        mix_degf_err_thres = self.get_param("mix_degf_err_thres")
        supply_degf_err_thres = self.get_param("supply_degf_err_thres")
        ahu_min_oa_dpr = self.get_param("ahu_min_oa_dpr")

        # Check analog outputs [data with units of %] are floats only
        columns_to_check = [
            economizer_sig_col,
            cooling_sig_col,
        ]
        self._apply_analog_checks(df, columns_to_check, check_greater_than_one=True)

        # Perform checks
        sat_fan_mat = abs(df[sat_col] - delta_t_supply_fan - df[mat_col])
        sat_mat_sqrted = np.sqrt(supply_degf_err_thres**2 + mix_degf_err_thres**2)

        combined_check = (
            (sat_fan_mat > sat_mat_sqrted)
            # Verify AHU is running in OS 3 cooling mode with minimum OA
            & (df[economizer_sig_col] > ahu_min_oa_dpr)
            & (df[cooling_sig_col] < 0.1)
        )

        # Set fault flag
        self._set_fault_flag(df, combined_check, "fc8_flag")

        return df
