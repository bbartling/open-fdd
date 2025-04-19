import numpy as np
import pandas as pd

from open_fdd.core.base_fault import BaseFaultCondition
from open_fdd.core.components import FaultInputColumn, InstanceAttribute
from open_fdd.core.exceptions import InvalidParameterError
from open_fdd.core.mixins import FaultConditionMixin

INPUT_COLS = [
    FaultInputColumn(
        name="clg_coil_enter_temp_col",
        constant_form="CLG_COIL_ENTER_TEMP_COL",
        description="Cooling coil entering air temperature",
        unit="°F",
        required=True,
        type=float,
    ),
    FaultInputColumn(
        name="clg_coil_leave_temp_col",
        constant_form="CLG_COIL_LEAVE_TEMP_COL",
        description="Cooling coil leaving air temperature",
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
        name="heating_sig_col",
        constant_form="HEATING_SIG_COL",
        description="Heating signal",
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
        name="supply_vfd_speed_col",
        constant_form="SUPPLY_VFD_SPEED_COL",
        description="Supply fan VFD speed",
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
        range=(0.0, 5.0),
    ),
    InstanceAttribute(
        name="coil_temp_enter_err_thres",
        constant_form="COIL_TEMP_ENTER_ERR_THRES",
        description="Cooling coil entering air temperature error threshold",
        unit="°F",
        type=float,
        range=(0.0, 10.0),
    ),
    InstanceAttribute(
        name="coil_temp_leave_err_thres",
        constant_form="COIL_TEMP_LEAV_ERR_THRES",
        description="Cooling coil leaving air temperature error threshold",
        unit="°F",
        type=float,
        range=(0.0, 10.0),
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


class FaultConditionFourteen(BaseFaultCondition, FaultConditionMixin):
    """Class provides the definitions for Fault Condition 14.
    Temperature drop across inactive cooling coil in OS1 (heating) and OS2 (economizer) modes.
    This fault checks if there is an unexpected temperature drop across the cooling coil
    when it should be inactive.

    py -3.12 -m pytest open_fdd/tests/ahu/test_ahu_fc14.py -rP -s
    """

    input_columns = INPUT_COLS
    fault_params = FAULT_PARAMS
    equation_string = (
        "fc14_flag = 1 if (CLG_LEAVE < CLG_ENTER - √(εENTER² + εLEAVE²)) "
        "in OS1 (heating) or OS2 (economizer) modes for N consecutive values else 0 \n"
    )
    description_string = (
        "Fault Condition 14: Temperature drop across inactive cooling coil "
        "in OS1 (heating) and OS2 (economizer) modes \n"
    )
    error_string = "One or more required columns are missing or None \n"

    @FaultConditionMixin._handle_errors
    def apply(self, df: pd.DataFrame) -> pd.DataFrame:
        """Apply the fault condition to the DataFrame."""
        # Apply common checks
        self._apply_common_checks(df)

        # Get column values using accessor methods
        cooling_sig_col = self.get_input_column("cooling_sig_col")
        heating_sig_col = self.get_input_column("heating_sig_col")
        economizer_sig_col = self.get_input_column("economizer_sig_col")
        supply_vfd_speed_col = self.get_input_column("supply_vfd_speed_col")
        clg_coil_enter_temp_col = self.get_input_column("clg_coil_enter_temp_col")
        clg_coil_leave_temp_col = self.get_input_column("clg_coil_leave_temp_col")

        # Get parameter values using accessor methods
        coil_temp_enter_err_thres = self.get_param("coil_temp_enter_err_thres")
        coil_temp_leave_err_thres = self.get_param("coil_temp_leave_err_thres")
        ahu_min_oa_dpr = self.get_param("ahu_min_oa_dpr")

        # Check analog outputs [data with units of %] are floats only
        columns_to_check = [
            cooling_sig_col,
            heating_sig_col,
            economizer_sig_col,
            supply_vfd_speed_col,
        ]
        self._apply_analog_checks(df, columns_to_check, check_greater_than_one=True)

        # Calculate the threshold for temperature drop
        temp_drop_threshold = np.sqrt(
            coil_temp_enter_err_thres**2 + coil_temp_leave_err_thres**2
        )

        # Check if there's a significant temperature drop across the cooling coil
        temp_drop = df[clg_coil_enter_temp_col] - df[clg_coil_leave_temp_col]
        significant_temp_drop = temp_drop > temp_drop_threshold

        # Check operating modes:
        # OS1: Heating mode (HTG > 0, CLG = 0, ECO = MIN_OA)
        os1_mode = (
            (df[heating_sig_col] > 0.0)
            & (df[cooling_sig_col] == 0.0)
            & (df[economizer_sig_col] <= ahu_min_oa_dpr)
        )

        # OS2: Economizer mode (HTG = 0, CLG = 0, ECO > MIN_OA)
        os2_mode = (
            (df[heating_sig_col] == 0.0)
            & (df[cooling_sig_col] == 0.0)
            & (df[economizer_sig_col] > ahu_min_oa_dpr)
        )

        # Combine conditions:
        # Fault occurs when there's a significant temperature drop across an inactive cooling coil
        # in either OS1 (heating) or OS2 (economizer) mode
        combined_check = significant_temp_drop & (os1_mode | os2_mode)

        # Set fault flag
        self._set_fault_flag(df, combined_check, "fc14_flag")

        return df
