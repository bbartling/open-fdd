import pandas as pd
from open_fdd.core.base_fault import BaseFaultCondition
from open_fdd.core.mixins import FaultConditionMixin

from open_fdd.core.components import FaultInputColumn, InstanceAttribute

INPUT_COLS = [
    FaultInputColumn(
        name="duct_static_col",
        constant_form="DUCT_STATIC_COL",
        description="Duct static pressure",
        unit="inches of water",
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
    FaultInputColumn(
        name="duct_static_setpoint_col",
        constant_form="DUCT_STATIC_SETPOINT_COL",
        description="Duct static pressure setpoint",
        unit="inches of water",
        required=True,
        type=float,
    ),
]

FAULT_PARAMS = [
    InstanceAttribute(
        name="duct_static_inches_err_thres",
        constant_form="DUCT_STATIC_INCHES_ERR_THRES",
        description="Duct static pressure error threshold",
        unit="inches of water",
        type=float,
    ),
    InstanceAttribute(
        name="vfd_speed_percent_max",
        constant_form="VFD_SPEED_PERCENT_MAX",
        description="Maximum VFD speed percentage",
        unit="%",
        type=float,
    ),
    InstanceAttribute(
        name="vfd_speed_percent_err_thres",
        constant_form="VFD_SPEED_PERCENT_ERR_THRES",
        description="VFD speed error threshold",
        unit="%",
        type=float,
    ),
]


class FaultConditionOne(BaseFaultCondition, FaultConditionMixin):
    """Class provides the definitions for Fault Condition 1.
    AHU low duct static pressure fan fault.

    py -3.12 -m pytest open_fdd/tests/ahu/test_ahu_fc1.py -rP -s
    """
    input_columns = INPUT_COLS
    fault_params = FAULT_PARAMS
    equation_string = "fc1_flag = 1 if (DP < DPSP - εDP) and (VFDSPD >= VFDSPD_max - εVFDSPD) for N consecutive values else 0 \n"
    description_string = (
         "Fault Condition 1: Duct static too low at fan at full speed \n"
    )
    
    error_string = "One or more required columns are missing or None \n"

    def _init_specific_attributes(self, dict_):
        # Initialize specific attributes
        self.required_columns = []
        required_column_map = {
            col.name: col for col in self.input_columns if col.required
        }
        for col in self.input_columns:
            setattr(self, col.name, dict_.get(col.constant_form, None))
            if col.required:
                self.required_columns.append(dict_.get(col.constant_form))

        for param in self.fault_params:
            setattr(self, param.name, dict_.get(param.constant_form, None))
        self.required_column_description = f"Required inputs are: {',\n'.join([f'{val.constant_form}: {val.description}' for val in required_column_map.values()])}\n"

    @FaultConditionMixin._handle_errors
    def apply(self, df: pd.DataFrame) -> pd.DataFrame:
        self._apply_common_checks(df)
        self._apply_analog_checks(df, [self.supply_vfd_speed_col])

        # Convert VFD speed from percentage to fraction if needed
        if (df[self.supply_vfd_speed_col] > 1.0).any():
            df[self.supply_vfd_speed_col] = df[self.supply_vfd_speed_col] / 100.0

        # Convert thresholds from percentage to fraction
        vfd_speed_max = self.vfd_speed_percent_max / 100.0
        vfd_speed_err_thres = self.vfd_speed_percent_err_thres / 100.0

        # Specific checks
        static_check = (
            df[self.duct_static_col]
            < df[self.duct_static_setpoint_col] - self.duct_static_inches_err_thres
        )
        fan_check = df[self.supply_vfd_speed_col] >= vfd_speed_max - vfd_speed_err_thres
        combined_check = static_check & fan_check

        self._set_fault_flag(df, combined_check, "fc1_flag")
        return df