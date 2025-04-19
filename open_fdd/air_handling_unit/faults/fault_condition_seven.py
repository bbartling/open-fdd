import pandas as pd

from open_fdd.core.base_fault import BaseFaultCondition
from open_fdd.core.components import FaultInputColumn, InstanceAttribute
from open_fdd.core.exceptions import InvalidParameterError, MissingColumnError
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
        name="sat_setpoint_col",
        constant_form="SAT_SETPOINT_COL",
        description="Supply air temperature setpoint",
        unit="°F",
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
        name="supply_degf_err_thres",
        constant_form="SUPPLY_DEGF_ERR_THRES",
        description="Supply air temperature error threshold",
        unit="°F",
        type=float,
        range=(0.0, 10.0),
    ),
]


class FaultConditionSeven(BaseFaultCondition, FaultConditionMixin):
    """Class provides the definitions for Fault Condition 7.
    Very similar to FC 13 but uses heating valve.
    Supply air temperature too low in full heating.

    py -3.12 -m pytest open_fdd/tests/ahu/test_ahu_fc7.py -rP -s
    """

    input_columns = INPUT_COLS
    fault_params = FAULT_PARAMS
    equation_string = (
        "fc7_flag = 1 if SAT < (SATSP - εSAT) in full heating mode "
        "and VFD speed > 0 for N consecutive values else 0 \n"
    )
    description_string = (
        "Fault Condition 7: Supply air temperature too low in full heating mode "
        "with heating valve fully open \n"
    )
    error_string = "One or more required columns are missing or None \n"

    @FaultConditionMixin._handle_errors
    def apply(self, df: pd.DataFrame) -> pd.DataFrame:
        """Apply the fault condition to the DataFrame."""
        # Apply common checks
        self._apply_common_checks(df)

        # Get column values using accessor methods
        sat_col = self.get_input_column("sat_col")
        sat_setpoint_col = self.get_input_column("sat_setpoint_col")
        supply_vfd_speed_col = self.get_input_column("supply_vfd_speed_col")
        heating_sig_col = self.get_input_column("heating_sig_col")

        # Get parameter values using accessor methods
        supply_degf_err_thres = self.get_param("supply_degf_err_thres")

        # Check analog outputs [data with units of %] are floats only
        columns_to_check = [supply_vfd_speed_col, heating_sig_col]
        self._apply_analog_checks(df, columns_to_check, check_greater_than_one=True)

        # Perform checks
        sat_check = df[sat_setpoint_col] - supply_degf_err_thres

        combined_check = (
            (df[sat_col] < sat_check)
            & (df[heating_sig_col] > 0.9)
            & (df[supply_vfd_speed_col] > 0)
        )

        # Set fault flag
        self._set_fault_flag(df, combined_check, "fc7_flag")

        return df
