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
        df["fc1_flag"] = operator.and_(
            df[self.duct_static_col]
            < (df[self.duct_static_setpoint_col] - self.duct_static_inches_err_thres),
            df[self.supply_vfd_speed_col]
            > (self.vfd_speed_percent_max - self.vfd_speed_percent_err_thres))
        return df


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
        df["fc2_flag"] = (df[self.mat_col] + self.mix_degf_err_thres
                < np.minimum(df[self.rat_col] - self.return_degf_err_thres,
                df[self.oat_col] - self.outdoor_degf_err_thres)).astype(int)
        return df


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
        df["fc3_flag"] = (df[self.mat_col] - self.mix_degf_err_thres
                > np.minimum(df[self.rat_col] + self.return_degf_err_thres,
                df[self.oat_col] + self.outdoor_degf_err_thres)).astype(int)
        return df


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

    # adds in these boolean columns to the dataframe
    def os_state_change_calcs(self, df):

        # AHU htg only mode based on OA damper @ min oa and only htg pid/vlv modulating
        df['heating_mode'] = df[self.heating_sig_col].gt(0.) \
            & df[self.cooling_sig_col].eq(0.) \
            & df[self.economizer_sig_col].eq(self.ahu_min_oa)

        # AHU econ only mode based on OA damper modulating and clg htg = zero
        df['econ_only_cooling_mode'] = df[self.economizer_sig_col].gt(self.ahu_min_oa) \
            & df[self.cooling_sig_col].eq(0.) \
            & df[self.heating_sig_col].eq(0.)

        # AHU econ+mech clg mode based on OA damper modulating for cooling and clg pid/vlv modulating
        df['econ_plus_mech_cooling_mode'] = df[self.economizer_sig_col].gt(90.) \
            & df[self.cooling_sig_col].gt(0.) \
            & df[self.heating_sig_col].eq(0.)

        # AHU mech mode based on OA damper @ min OA and clg pid/vlv modulating
        df['mech_cooling_only_mode'] = df[self.economizer_sig_col].eq(self.ahu_min_oa) \
            & df[self.cooling_sig_col].gt(0.) \
            & df[self.heating_sig_col].eq(0.)

        df = df[[
            'heating_mode',
            'econ_only_cooling_mode',
            'econ_plus_mech_cooling_mode',
            'mech_cooling_only_mode'
            ]]

        df = df.astype(int)

        # calc changes per hour for modes
        # https://stackoverflow.com/questions/69979832/pandas-consecutive-boolean-event-rollup-time-series

        df = df.resample('H').apply(
            lambda x: (x.eq(1) & x.shift().ne(1)).sum())

        df["fc4_flag"] = df[df.columns].gt(
            self.delta_os_max).any(1).astype(int)
        return df

    def apply(self, df: pd.DataFrame) -> pd.DataFrame:
        df = self.os_state_change_calcs(df)
        return df


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
        df["fc5_flag"] = ((df[self.sat_col] + self.supply_degf_err_thres)
                <= (df[self.mat_col] - self.mix_degf_err_thres + self.delta_t_supply_fan))
        return df


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
        vav_total_flow_col: float,
        mat_col: str,
        oat_col: str,
        rat_col: str,
    ):
        self.airflow_err_thres = airflow_err_thres
        self.ahu_min_cfm_stp = ahu_min_cfm_stp
        self.oat_degf_err_thres = oat_degf_err_thres
        self.rat_degf_err_thres = rat_degf_err_thres
        self.oat_rat_delta_min = oat_rat_delta_min
        self.vav_total_flow_col = vav_total_flow_col
        self.mat_col = mat_col
        self.oat_col = oat_col
        self.rat_col = rat_col

    def additional_pandas_calcs(self, df):
        df['rat_minus_oat'] = abs(df[self.rat_col] - df[self.oat_col])
        df['percent_oa_calc'] = (df[self.mat_col] - df[self.rat_col]) / \
            (df[self.oat_col] - df[self.rat_col])
        df['percent_oa_calc'] = df['percent_oa_calc'].apply(
            lambda x: x if x > 0 else 0)
        df['perc_OAmin'] = (self.ahu_min_cfm_stp /
                            df[self.vav_total_flow_col]) * 100
        df['percent_oa_calc_minus_perc_OAmin'] = abs(
            df['percent_oa_calc'] - df['perc_OAmin'])

        df['fc6_flag'] = operator.and_(df['rat_minus_oat'] >= self.oat_rat_delta_min,
                             df['percent_oa_calc_minus_perc_OAmin']
                             > self.airflow_err_thres
                             ).astype(int)

        df = df[[
            "percent_oa_calc",
            "perc_OAmin",
            self.vav_total_flow_col,
            "fc6_flag"
            ]]

        return df

    def apply(self, df: pd.DataFrame) -> pd.DataFrame:
        df = self.additional_pandas_calcs(df)
        return df


class FaultConditionSeven:
    """Class provides the definitions for Fault Condition 7.
        Very similar to FC 13 but uses heating valve
    """

    def __init__(
        self,
        sat_degf_err_thres: float,
        sat_col: str,
        satsp_col: str,
        htg_col: str,
    ):
        self.sat_degf_err_thres = sat_degf_err_thres
        self.sat_col = sat_col
        self.satsp_col = satsp_col
        self.htg_col = htg_col

    def apply(self, df: pd.DataFrame) -> pd.DataFrame:
        df["fc7_flag"] = operator.and_(df[self.sat_col]
                            < df[self.satsp_col] - self.sat_degf_err_thres,
                            df[self.htg_col] >= 99).astype(int)
        return df


class FaultConditionEleven:
    """Class provides the definitions for Fault Condition 11."""

    def __init__(
        self,
		delta_supply_fan: float,
		oat_err_thres: float,
		supply_err_thres: float,
		satsp_col: str,
        oat_col: str,
    ):
        self.delta_supply_fan = delta_supply_fan
        self.oat_err_thres = oat_err_thres
        self.supply_err_thres = supply_err_thres
        self.satsp_col = satsp_col
        self.oat_col = oat_col

        
    def apply(self, df: pd.DataFrame) -> pd.DataFrame:
        df['oat_minus_oaterror'] = df[self.oat_col] - self.oat_err_thres
        df['satsp_delta_saterr'] = df[self.satsp_col] - \
            self.delta_supply_fan - self.supply_err_thres

        df['fc11_flag'] = (df.oat_minus_oaterror 
            < df.satsp_delta_saterr).astype(int)

        df = df[[
            'satsp',
            'oat',
            'fc11_flag'
        ]]
        return df


class FaultConditionTwelve:
    """Class provides the definitions for Fault Condition 12."""

    def __init__(
        self,
		delta_supply_fan: float,
		mix_err_thres: float,
		supply_err_thres: float,
        sat_col: str,
        mat_col: str,
    ):
        self.delta_supply_fan = delta_supply_fan
        self.mix_err_thres = mix_err_thres
        self.supply_err_thres = supply_err_thres
        self.sat_col = sat_col
        self.mat_col = mat_col

    def apply(self, df: pd.DataFrame) -> pd.DataFrame:
        df['sat_minus_saterr_delta_supply_fan'] = df[self.sat_col] - \
            self.supply_err_thres - self.delta_supply_fan
        df['mat_plus_materr'] = df[self.mat_col] + self.mix_err_thres
        df["fc12_flag"] = (df['sat_minus_saterr_delta_supply_fan']
            >= df['mat_plus_materr']).astype(int)
        df = df[[
            self.sat_col,
            self.mat_col,
            "fc12_flag"
        ]]
        return df
    
    
class FaultConditionThirteen:
    """Class provides the definitions for Fault Condition 13.
        Very similar to FC 13 but uses cooling valve
    """

    def __init__(
        self,
        sat_degf_err_thres: float,
        sat_col: str,
        satsp_col: str,
        clg_col: str,
    ):
        self.sat_degf_err_thres = sat_degf_err_thres
        self.sat_col = sat_col
        self.satsp_col = satsp_col
        self.clg_col = clg_col

    def apply(self, df: pd.DataFrame) -> pd.DataFrame:
        df["fc13_flag"] = operator.and_(df[self.sat_col]
                            < df[self.satsp_col] + self.sat_degf_err_thres,
                            df[self.clg_col] >= 99).astype(int)
        return df
		