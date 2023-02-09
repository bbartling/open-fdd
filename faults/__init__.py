import operator
import pandas as pd


class FaultConditionOne:
    def __init__(
        self,
        vfd_speed_percent_err_thres: float,
        vfd_speed_percent_max: float,
        duct_static_inches_err_thres: float,
        duct_static_col: str,
        supply_vfd_speed_col: str,
        duct_static_setpoint_col: str,

    ):
        self.vfd_speed_percent_err_thres = vfd_speed_percent_err_thres
        self.vfd_speed_percent_max = vfd_speed_percent_max
        self.duct_static_inches_err_thres = duct_static_inches_err_thres
        self.duct_static_col = duct_static_col
        self.supply_vfd_speed_col = supply_vfd_speed_col
        self.duct_static_setpoint_col = duct_static_setpoint_col

    def apply(self, df: pd.DataFrame) -> pd.DataFrame:
        return operator.and_(
            df[self.duct_static_col]
            < (df[self.duct_static_setpoint_col] - self.duct_static_inches_err_thres),
            df[self.supply_vfd_speed_col]
            > (self.vfd_speed_percent_max - self.vfd_speed_percent_err_thres),
        )
