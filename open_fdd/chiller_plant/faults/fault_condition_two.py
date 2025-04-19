import pandas as pd

from open_fdd.core.base_fault import BaseFaultCondition
from open_fdd.core.components import FaultInputColumn, InstanceAttribute
from open_fdd.core.mixins import FaultConditionMixin

INPUT_COLS = [
    FaultInputColumn(
        name="flow_col",
        constant_form="FLOW_COL",
        description="Flow meter reading",
        unit="GPM",
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
]

FAULT_PARAMS = [
    InstanceAttribute(
        name="flow_error_threshold",
        constant_form="FLOW_ERROR_THRESHOLD",
        description="Flow error threshold",
        unit="GPM",
        type=float,
        range=(0.0, 1000.0),
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
        name="pump_speed_percent_err_thres",
        constant_form="PUMP_SPEED_PERCENT_ERR_THRES",
        description="Pump speed error threshold",
        unit="%",
        type=float,
        range=(0.0, 1.0),
    ),
]


class FaultConditionTwo(BaseFaultCondition, FaultConditionMixin):
    """
    Class provides the definitions for Fault Condition 2.
    Primary chilled water flow is too high with the chilled water pump running at high speed.

    py -3.12 -m pytest open_fdd/tests/chiller/test_chiller_fc2.py -rP -s
    """

    input_columns = INPUT_COLS
    fault_params = FAULT_PARAMS
    equation_string = (
        "fc2_flag = 1 if (FLOW > εFM) and (PUMPSPD >= PUMPSPD_max - εPUMPSPD) "
        "for N consecutive values else 0 \n"
    )
    description_string = "Fault Condition 2: Primary chilled water flow is too high with the pump running at high speed \n"
    error_string = "One or more required columns are missing or None \n"

    @FaultConditionMixin._handle_errors
    def apply(self, df: pd.DataFrame) -> pd.DataFrame:
        self._apply_common_checks(df)

        # Get column values using accessor methods
        flow_col = self.get_input_column("flow_col")
        pump_speed_col = self.get_input_column("pump_speed_col")

        # Get parameter values using accessor methods
        flow_error_threshold = self.get_param("flow_error_threshold")
        pump_speed_percent_max = self.get_param("pump_speed_percent_max")
        pump_speed_percent_err_thres = self.get_param("pump_speed_percent_err_thres")

        # Check analog outputs are floats only
        columns_to_check = [pump_speed_col]
        self._apply_analog_checks(df, columns_to_check)

        # Perform checks
        flow_check = df[flow_col] < flow_error_threshold
        pump_check = (
            df[pump_speed_col] >= pump_speed_percent_max - pump_speed_percent_err_thres
        )

        # Combined condition check
        combined_check = flow_check & pump_check

        # Set fault flag
        self._set_fault_flag(df, combined_check, "fc2_flag")

        return df
