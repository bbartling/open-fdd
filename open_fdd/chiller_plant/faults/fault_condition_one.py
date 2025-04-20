import pandas as pd

from open_fdd.core.base_fault import BaseFaultCondition
from open_fdd.core.components import FaultInputColumn, InstanceAttribute
from open_fdd.core.mixins import FaultConditionMixin

INPUT_COLS = [
    FaultInputColumn(
        name="diff_pressure_col",
        constant_form="DIFF_PRESSURE_COL",
        description="Differential pressure",
        unit="PSI",
        required=True,
        type=str,
    ),
    FaultInputColumn(
        name="pump_speed_col",
        constant_form="PUMP_SPEED_COL",
        description="Pump speed",
        unit="%",
        required=True,
        type=str,
    ),
    FaultInputColumn(
        name="diff_pressure_setpoint_col",
        constant_form="DIFF_PRESSURE_SETPOINT_COL",
        description="Differential pressure setpoint",
        unit="PSI",
        required=True,
        type=str,
    ),
]

FAULT_PARAMS = [
    InstanceAttribute(
        name="pump_speed_percent_err_thres",
        constant_form="PUMP_SPEED_PERCENT_ERR_THRES",
        description="Pump speed error threshold",
        unit="%",
        type=float,
        range=(0.0, 1.0),
    ),
    InstanceAttribute(
        name="pump_speed_percent_max",
        constant_form="PUMP_SPEED_PERCENT_MAX",
        description="Maximum pump speed percentage",
        unit="%",
        type=float,
        range=(0.0, 1.0),
    ),
    InstanceAttribute(
        name="diff_pressure_psi_err_thres",
        constant_form="DIFF_PRESSURE_PSI_ERR_THRES",
        description="Differential pressure error threshold",
        unit="PSI",
        type=float,
        range=(0.0, 100.0),
    ),
]


class FaultConditionOne(BaseFaultCondition, FaultConditionMixin):
    """Class provides the definitions for Fault Condition for pumps.
    Variable pump does not meet differential pressure setpoint.

    py -3.12 -m pytest open_fdd/tests/chiller/test_chiller_fc1.py -rP -s
    """

    input_columns = INPUT_COLS
    fault_params = FAULT_PARAMS
    equation_string = (
        "fc_pump_flag = 1 if (DP < DPSP - εDP) and (PUMPSPD >= PUMPSPD_max - εPUMPSPD) "
        "for N consecutive values else 0 \n"
    )
    description_string = (
        "Fault Condition: Differential pressure too low with pump at full speed \n"
    )
    error_string = "One or more required columns are missing or None \n"

    @FaultConditionMixin._handle_errors
    def apply(self, df: pd.DataFrame) -> pd.DataFrame:
        self._apply_common_checks(df)

        # Get column values using accessor methods
        diff_pressure_col = self.get_input_column("diff_pressure_col")
        pump_speed_col = self.get_input_column("pump_speed_col")
        diff_pressure_setpoint_col = self.get_input_column("diff_pressure_setpoint_col")

        # Get parameter values using accessor methods
        pump_speed_percent_max = self.get_param("pump_speed_percent_max")
        pump_speed_percent_err_thres = self.get_param("pump_speed_percent_err_thres")
        diff_pressure_psi_err_thres = self.get_param("diff_pressure_psi_err_thres")

        # Check analog outputs are floats only
        columns_to_check = [pump_speed_col]
        self._apply_analog_checks(df, columns_to_check)

        # Perform checks
        pressure_check = (
            df[diff_pressure_col]
            < df[diff_pressure_setpoint_col] - diff_pressure_psi_err_thres
        )
        pump_check = (
            df[pump_speed_col] >= pump_speed_percent_max - pump_speed_percent_err_thres
        )

        # Combined condition check
        combined_check = pressure_check & pump_check

        # Set fault flag
        self._set_fault_flag(df, combined_check, "fc_pump_flag")

        return df
