import pandas as pd

from open_fdd.core.base_fault import BaseFaultCondition
from open_fdd.core.components import FaultInputColumn, InstanceAttribute
from open_fdd.core.exceptions import InvalidParameterError
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
        name="mix_degf_err_thres",
        constant_form="MIX_DEGF_ERR_THRES",
        description="Mixed air temperature error threshold",
        unit="°F",
        type=float,
        range=(0.0, 10.0),
    ),
    InstanceAttribute(
        name="supply_degf_err_thres",
        constant_form="SUPPLY_DEGF_ERR_THRES",
        description="Supply air temperature error threshold",
        unit="°F",
        type=float,
        range=(0.0, 10.0),
    ),
    InstanceAttribute(
        name="delta_t_supply_fan",
        constant_form="DELTA_T_SUPPLY_FAN",
        description="Temperature rise across supply fan",
        unit="°F",
        type=float,
        range=(0.0, 5.0),
    ),
]


class FaultConditionFive(BaseFaultCondition, FaultConditionMixin):
    """Class provides the definitions for Fault Condition 5.
    SAT too low; should be higher than MAT in HTG MODE
    --Broken heating valve or other mechanical issue
    related to heat valve not working as designed

    py -3.12 -m pytest open_fdd/tests/ahu/test_ahu_fc5.py -rP -s
    """

    input_columns = INPUT_COLS
    fault_params = FAULT_PARAMS
    equation_string = (
        "fc5_flag = 1 if (SAT + εSAT <= MAT - εMAT + ΔT_supply_fan) and "
        "(heating signal > 0) and (VFDSPD > 0) for N consecutive values else 0 \n"
    )
    description_string = (
        "Fault Condition 5: SAT too low; should be higher than MAT in HTG MODE, "
        "potential broken heating valve or mechanical issue \n"
    )
    error_string = "One or more required columns are missing or None \n"

    @FaultConditionMixin._handle_errors
    def apply(self, df: pd.DataFrame) -> pd.DataFrame:
        """Apply the fault condition to the DataFrame."""
        # Apply common checks
        self._apply_common_checks(df)

        # Get column values using accessor methods
        supply_vfd_speed_col = self.get_input_column("supply_vfd_speed_col")
        heating_sig_col = self.get_input_column("heating_sig_col")
        sat_col = self.get_input_column("sat_col")
        mat_col = self.get_input_column("mat_col")

        # Get parameter values using accessor methods
        supply_degf_err_thres = self.get_param("supply_degf_err_thres")
        mix_degf_err_thres = self.get_param("mix_degf_err_thres")
        delta_t_supply_fan = self.get_param("delta_t_supply_fan")

        # Check analog outputs [data with units of %] are floats only
        columns_to_check = [supply_vfd_speed_col, heating_sig_col]
        self._apply_analog_checks(df, columns_to_check, check_greater_than_one=True)

        # Perform checks
        sat_check = df[sat_col] + supply_degf_err_thres
        mat_check = df[mat_col] - mix_degf_err_thres + delta_t_supply_fan

        combined_check = (
            (sat_check <= mat_check)
            & (df[heating_sig_col] > 0.01)
            & (df[supply_vfd_speed_col] > 0.01)
        )

        # Set fault flag
        self._set_fault_flag(df, combined_check, "fc5_flag")

        return df
