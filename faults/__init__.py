import operator
import pandas as pd
import numpy as np



class FaultConditionOne:
    """Class provides the definitions for Fault Condition 1."""

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



class FaultConditionTwo:
    """Class provides the definitions for Fault Condition 2."""

    def __init__(
        self,
        mix_degf_err_thres: float,
        return_degf_err_thres: float,
        outdoor_degf_err_thres: float,
        mat_col: str,
        rat_col: str,
        oat_col: str,
    ):
        self.mix_degf_err_thres = mix_degf_err_thres
        self.return_degf_err_thres = return_degf_err_thres
        self.outdoor_degf_err_thres = outdoor_degf_err_thres
        self.mat_col = mat_col
        self.rat_col = rat_col
        self.oat_col = oat_col

    def apply(self, df: pd.DataFrame) -> pd.DataFrame:
        return (df[self.mat_col] + self.mix_degf_err_thres
                < np.minimum(df[self.rat_col] - self.return_degf_err_thres,
                df[self.oat_col] - self.outdoor_degf_err_thres)
        )
        
        

class FaultConditionThree:
    """Class provides the definitions for Fault Condition 3."""

    def __init__(
        self,
        mix_degf_err_thres: float,
        return_degf_err_thres: float,
        outdoor_degf_err_thres: float,
        mat_col: str,
        rat_col: str,
        oat_col: str,
    ):
        self.mix_degf_err_thres = mix_degf_err_thres
        self.return_degf_err_thres = return_degf_err_thres
        self.outdoor_degf_err_thres = outdoor_degf_err_thres
        self.mat_col = mat_col
        self.rat_col = rat_col
        self.oat_col = oat_col


    def apply(self, df: pd.DataFrame) -> pd.DataFrame:
        return (df[self.mat_col] - self.mix_degf_err_thres
                > np.minimum(df[self.rat_col] + self.return_degf_err_thres,
                df[self.oat_col] + self.outdoor_degf_err_thres)
        )



class FaultConditionFour:
    """Class provides the definitions for Fault Condition 4."""

    def __init__(
        self,
        delta_os_max: float,
        ahu_min_oa: float,
        economizer_sig_col: str,
        heating_sig_col: str,
        cooling_sig_col: str,
    ):
        self.delta_os_max = delta_os_max
        self.ahu_min_oa = ahu_min_oa
        self.economizer_sig_col = economizer_sig_col
        self.heating_sig_col = heating_sig_col
        self.cooling_sig_col = cooling_sig_col
        
    def os_state_change_calcs(self,df):
        df['heating_mode'] = df['heating_sig'].gt(0.)
        df['econ_mode'] = df['economizer_sig'].gt(df['ahu_min_oa']) & df['cooling_sig'].eq(0.)
        df['econ_cooling_mode'] = df['economizer_sig'].gt(df['ahu_min_oa']) & df['cooling_sig'].gt(0.)
        df['mech_cooling_mode'] = df['economizer_sig'].eq(df['ahu_min_oa']) & df['cooling_sig'].gt(0.)
        return df

    def apply(self, df: pd.DataFrame) -> pd.DataFrame:
        return self.os_state_change_calcs(df)



class FaultConditionFive:
    """Class provides the definitions for Fault Condition 5."""

    def __init__(
        self,
        mix_degf_err_thres: float,
        supply_degf_err_thres: float,
        delta_t_supply_fan: float,
        mat_col: str,
        sat_col: str,
    ):
        self.mix_degf_err_thres = mix_degf_err_thres
        self.supply_degf_err_thres = supply_degf_err_thres
        self.delta_t_supply_fan = delta_t_supply_fan
        self.mat_col = mat_col
        self.sat_col = sat_col


    def apply(self, df: pd.DataFrame) -> pd.DataFrame:
        return ((df[self.sat_col] + df[self.supply_degf_err_thres]) 
                <= (df[self.mat_col] - df[self.mix_degf_err_thres] + df[self.delta_t_supply_fan])
                )
        
        

class FaultConditionSix:
    """Class provides the definitions for Fault Condition 6.
        Requires an externally calculated VAV box air flow summation 
        read from each VAV box air flow transmitter or supply fan AFMS
    """

    def __init__(
        self,
        airflow_err_thres: float,
        ahu_min_cfm_stp: float,
        oat_degf_err_thres: float,
        rat_degf_err_thres: float,
        oat_rat_delta_min: float,
        vav_total_flow: float,
        mat_col: str,
        oat_col: str,
        rat_col: str,
    ):
        self.airflow_err_thres = airflow_err_thres
        self.ahu_min_cfm_stp = ahu_min_cfm_stp
        self.oat_degf_err_thres = oat_degf_err_thres
        self.rat_degf_err_thres = rat_degf_err_thres
        self.oat_rat_delta_min = oat_rat_delta_min
        self.vav_total_flow = vav_total_flow
        self.mat_col = mat_col
        self.oat_col = oat_col
        self.rat_col = rat_col

        # additional calculations
    def additional_pandas_calcs(self,df):
        df['rat_minus_oat'] = abs(df['rat'] - df['oat'])
        df['percent_oa_calc'] = (df['mat'] - df['rat']) / (df['oat'] - df['rat'])
        df['percent_oa_calc'] = df['percent_oa_calc'].apply(lambda x : x if x > 0 else 0)
        df['perc_OAmin'] = self.airflow_err_thres / df['vav_total_flow']
        df['percent_oa_calc_minus_perc_OAmin'] = abs(df['percent_oa_calc'] - df['perc_OAmin'])
        return df
        
        
    def apply(self, df: pd.DataFrame) -> pd.DataFrame:
        df = self.additional_pandas_calcs(df)
        return operator.and_(df[self.rat_minus_oat] >= df[self.oat_rat_delta_min],
                            df[self.percent_oa_calc_minus_perc_OAmin] 
                            > df[self.airflow_err_thres]
                            )