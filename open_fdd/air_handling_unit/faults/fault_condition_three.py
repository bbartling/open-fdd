import numpy as np
import pandas as pd

from open_fdd.core.base_fault import BaseFaultCondition
from open_fdd.core.components import FaultInputColumn, InstanceAttribute
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
        name="rat_col",
        constant_form="RAT_COL",
        description="Return air temperature",
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
]


class FaultConditionThree(BaseFaultCondition, FaultConditionMixin):
    """Class provides the definitions for Fault Condition 3.
    Mix temperature too high; should be between outside and return air.
    """

    input_columns = INPUT_COLS
    fault_params = FAULT_PARAMS
    equation_string = "fc3_flag = 1 if (MAT - εMAT > max(RAT + εRAT, OAT + εOAT)) and (VFDSPD > 0) for N consecutive values else 0 \n"
    description_string = "Fault Condition 3: Mix temperature too high; should be between outside and return air \n"
    error_string = "One or more required columns are missing or None \n"

    def _init_specific_attributes(self, dict_):
        # Use the BaseFaultCondition's _init_specific_attributes method
        super()._init_specific_attributes(dict_)

    @FaultConditionMixin._handle_errors
    def apply(self, df: pd.DataFrame) -> pd.DataFrame:
        self._apply_common_checks(df)

        # Get column values using accessor methods
        supply_vfd_speed_col = self.get_input_column("supply_vfd_speed_col")
        mat_col = self.get_input_column("mat_col")
        rat_col = self.get_input_column("rat_col")
        oat_col = self.get_input_column("oat_col")

        # Get parameter values using accessor methods
        mix_degf_err_thres = self.get_param("mix_degf_err_thres")
        return_degf_err_thres = self.get_param("return_degf_err_thres")
        outdoor_degf_err_thres = self.get_param("outdoor_degf_err_thres")

        self._apply_analog_checks(
            df, [supply_vfd_speed_col], check_greater_than_one=True
        )

        # Specific checks
        mat_check = df[mat_col] - mix_degf_err_thres
        temp_max_check = np.maximum(
            df[rat_col] + return_degf_err_thres,
            df[oat_col] + outdoor_degf_err_thres,
        )
        combined_check = (mat_check > temp_max_check) & (
            df[supply_vfd_speed_col] > 0.01
        )

        self._set_fault_flag(df, combined_check, "fc3_flag")
        return df
