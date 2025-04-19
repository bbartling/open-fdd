import numpy as np
import pandas as pd

from open_fdd.core.base_fault import BaseFaultCondition
from open_fdd.core.components import FaultInputColumn, InstanceAttribute
from open_fdd.core.exceptions import InvalidParameterError
from open_fdd.core.mixins import FaultConditionMixin

INPUT_COLS = [
    FaultInputColumn(
        name="oat_col",
        constant_form="OAT_COL",
        description="Outside air temperature",
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
        name="outdoor_degf_err_thres",
        constant_form="OUTDOOR_DEGF_ERR_THRES",
        description="Outdoor air temperature error threshold",
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
]


class FaultConditionTen(BaseFaultCondition, FaultConditionMixin):
    """Class provides the definitions for Fault Condition 10.
    Outdoor air temperature and mix air temperature should
    be approx equal in economizer plus mech cooling mode.

    py -3.12 -m pytest open_fdd/tests/ahu/test_ahu_fc10.py -rP -s
    """

    input_columns = INPUT_COLS
    fault_params = FAULT_PARAMS
    equation_string = (
        "fc10_flag = 1 if |OAT - MAT| > √(εOAT² + εMAT²) in "
        "economizer + mech cooling mode for N consecutive values else 0 \n"
    )
    description_string = (
        "Fault Condition 10: Outdoor air temperature and mixed air temperature "
        "should be approximately equal in economizer plus mechanical cooling mode \n"
    )
    error_string = "One or more required columns are missing or None \n"

    @FaultConditionMixin._handle_errors
    def apply(self, df: pd.DataFrame) -> pd.DataFrame:
        """Apply the fault condition to the DataFrame."""
        # Apply common checks
        self._apply_common_checks(df)

        # Get column values using accessor methods
        oat_col = self.get_input_column("oat_col")
        mat_col = self.get_input_column("mat_col")
        cooling_sig_col = self.get_input_column("cooling_sig_col")
        economizer_sig_col = self.get_input_column("economizer_sig_col")

        # Get parameter values using accessor methods
        outdoor_degf_err_thres = self.get_param("outdoor_degf_err_thres")
        mix_degf_err_thres = self.get_param("mix_degf_err_thres")

        # Check analog outputs [data with units of %] are floats only
        columns_to_check = [
            economizer_sig_col,
            cooling_sig_col,
        ]
        self._apply_analog_checks(df, columns_to_check, check_greater_than_one=True)

        # Perform calculations
        abs_mat_minus_oat = abs(df[mat_col] - df[oat_col])
        mat_oat_sqrted = np.sqrt(mix_degf_err_thres**2 + outdoor_degf_err_thres**2)

        combined_check = (
            (abs_mat_minus_oat > mat_oat_sqrted)
            # Verify AHU is running in OS 3 cooling mode with minimum OA
            & (df[cooling_sig_col] > 0.01)
            & (df[economizer_sig_col] > 0.9)
        )

        # Set fault flag
        self._set_fault_flag(df, combined_check, "fc10_flag")

        return df
