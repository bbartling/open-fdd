import pandas as pd

from open_fdd.core.base_fault import BaseFaultCondition
from open_fdd.core.components import FaultInputColumn, InstanceAttribute
from open_fdd.core.exceptions import InvalidParameterError
from open_fdd.core.mixins import FaultConditionMixin

INPUT_COLS = [
    FaultInputColumn(
        name="sat_setpoint_col",
        constant_form="SAT_SETPOINT_COL",
        description="Supply air temperature setpoint",
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
        range=(0.0, 5.0),
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
        name="supply_degf_err_thres",
        constant_form="SUPPLY_DEGF_ERR_THRES",
        description="Supply air temperature error threshold",
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


class FaultConditionNine(BaseFaultCondition, FaultConditionMixin):
    """Class provides the definitions for Fault Condition 9.
    Outside air temperature too high in free cooling without
    additional mechanical cooling in economizer mode.

    py -3.12 -m pytest open_fdd/tests/ahu/test_ahu_fc9.py -rP -s
    """

    input_columns = INPUT_COLS
    fault_params = FAULT_PARAMS
    equation_string = (
        "fc9_flag = 1 if OAT > (SATSP - ΔT_fan + εSAT) "
        "in free cooling mode for N consecutive values else 0 \n"
    )
    description_string = (
        "Fault Condition 9: Outside air temperature too high in free cooling mode "
        "without additional mechanical cooling in economizer mode \n"
    )
    error_string = "One or more required columns are missing or None \n"

    @FaultConditionMixin._handle_errors
    def apply(self, df: pd.DataFrame) -> pd.DataFrame:
        """Apply the fault condition to the DataFrame."""
        # Apply common checks
        self._apply_common_checks(df)

        # Get column values using accessor methods
        oat_col = self.get_input_column("oat_col")
        sat_setpoint_col = self.get_input_column("sat_setpoint_col")
        economizer_sig_col = self.get_input_column("economizer_sig_col")
        cooling_sig_col = self.get_input_column("cooling_sig_col")

        # Get parameter values using accessor methods
        outdoor_degf_err_thres = self.get_param("outdoor_degf_err_thres")
        delta_t_supply_fan = self.get_param("delta_t_supply_fan")
        supply_degf_err_thres = self.get_param("supply_degf_err_thres")
        ahu_min_oa_dpr = self.get_param("ahu_min_oa_dpr")

        # Check analog outputs [data with units of %] are floats only
        columns_to_check = [
            economizer_sig_col,
            cooling_sig_col,
        ]
        self._apply_analog_checks(df, columns_to_check, check_greater_than_one=True)

        # Perform calculations
        oat_minus_oaterror = df[oat_col] - outdoor_degf_err_thres
        satsp_delta_saterr = (
            df[sat_setpoint_col] - delta_t_supply_fan + supply_degf_err_thres
        )

        combined_check = (
            (oat_minus_oaterror > satsp_delta_saterr)
            # verify AHU is in OS2 only free cooling mode
            & (df[economizer_sig_col] > ahu_min_oa_dpr)
            & (df[cooling_sig_col] < 0.1)
        )

        # Set fault flag
        self._set_fault_flag(df, combined_check, "fc9_flag")

        return df
