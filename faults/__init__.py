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
        troubleshoot=False
    ):
        self.vfd_speed_percent_err_thres = vfd_speed_percent_err_thres
        self.vfd_speed_percent_max = vfd_speed_percent_max
        self.duct_static_inches_err_thres = duct_static_inches_err_thres
        self.duct_static_col = duct_static_col
        self.supply_vfd_speed_col = supply_vfd_speed_col
        self.duct_static_setpoint_col = duct_static_setpoint_col
        self.troubleshoot = troubleshoot

    def apply(self, df: pd.DataFrame) -> pd.DataFrame:
        df['static_check_'] = (
            df[self.duct_static_col] < df[self.duct_static_setpoint_col] - self.duct_static_inches_err_thres)
        df['fan_check_'] = (df[self.supply_vfd_speed_col] >=
                            self.vfd_speed_percent_max - self.vfd_speed_percent_err_thres)

        df["fc1_flag"] = (df['static_check_'] & df['fan_check_']).astype(int)

        if self.troubleshoot:
            print("Troubleshoot mode enabled - not removing helper columns")

        else:
            del df['static_check_']
            del df['fan_check_']

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
        fan_vfd_speed_col: str,
        troubleshoot=False
    ):
        self.mix_degf_err_thres = mix_degf_err_thres
        self.return_degf_err_thres = return_degf_err_thres
        self.outdoor_degf_err_thres = outdoor_degf_err_thres
        self.mat_col = mat_col
        self.rat_col = rat_col
        self.oat_col = oat_col
        self.fan_vfd_speed_col = fan_vfd_speed_col
        self.troubleshoot = troubleshoot

    def apply(self, df: pd.DataFrame) -> pd.DataFrame:

        df['mat_check'] = df[self.mat_col] + self.mix_degf_err_thres
        df['temp_min_check'] = np.minimum(df[self.rat_col] - self.return_degf_err_thres,
                                          df[self.oat_col] - self.outdoor_degf_err_thres)

        df["fc2_flag"] = (
            (df['mat_check'] < df['temp_min_check'])

            # this fault is supposed to contain OS state 5
            # confirm with G36 fault author adding in fan status okay
            & (df[self.fan_vfd_speed_col] > .01)
        ).astype(int)

        if self.troubleshoot:
            print("Troubleshoot mode enabled - not removing helper columns")

        else:
            del df['mat_check']
            del df['temp_min_check']

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
        fan_vfd_speed_col: str,
        troubleshoot=False
    ):
        self.mix_degf_err_thres = mix_degf_err_thres
        self.return_degf_err_thres = return_degf_err_thres
        self.outdoor_degf_err_thres = outdoor_degf_err_thres
        self.mat_col = mat_col
        self.rat_col = rat_col
        self.oat_col = oat_col
        self.fan_vfd_speed_col = fan_vfd_speed_col
        self.troubleshoot = troubleshoot

    def apply(self, df: pd.DataFrame) -> pd.DataFrame:

        df['mat_check'] = df[self.mat_col] - self.mix_degf_err_thres
        df['temp_min_check'] = np.maximum(df[self.rat_col] + self.return_degf_err_thres,
                                          df[self.oat_col] + self.outdoor_degf_err_thres)

        df["fc3_flag"] = (
            (df['mat_check'] > df['temp_min_check'])

            # this fault is supposed to contain OS state 5
            # confirm with G36 fault author adding in fan status okay
            & (df[self.fan_vfd_speed_col] > .01)
        ).astype(int)

        if self.troubleshoot:
            print("Troubleshoot mode enabled - not removing helper columns")

        else:
            del df['mat_check']
            del df['temp_min_check']

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
        fan_vfd_speed_col: str,
        troubleshoot=False
    ):
        self.delta_os_max = delta_os_max
        self.ahu_min_oa = ahu_min_oa
        self.economizer_sig_col = economizer_sig_col
        self.heating_sig_col = heating_sig_col
        self.cooling_sig_col = cooling_sig_col
        self.fan_vfd_speed_col = fan_vfd_speed_col
        self.troubleshoot = troubleshoot

    # adds in these boolean columns to the dataframe
    def os_state_change_calcs(self, df):

        # AHU htg only mode based on OA damper @ min oa and only htg pid/vlv modulating
        df['heating_mode'] = (
            (df[self.heating_sig_col] > 0)
            & (df[self.cooling_sig_col] == 0)
            & (df[self.fan_vfd_speed_col] > 0)
            & (df[self.economizer_sig_col] == self.ahu_min_oa)
        )

        # AHU econ only mode based on OA damper modulating and clg htg = zero
        df['econ_only_cooling_mode'] = (
            (df[self.heating_sig_col] == 0)
            & (df[self.cooling_sig_col] == 0)
            & (df[self.fan_vfd_speed_col] > 0)
            & (df[self.economizer_sig_col] > self.ahu_min_oa)
        )

        # AHU econ+mech clg mode based on OA damper modulating for cooling and clg pid/vlv modulating
        df['econ_plus_mech_cooling_mode'] = (
            (df[self.heating_sig_col] == 0)
            & (df[self.cooling_sig_col] > 0)
            & (df[self.fan_vfd_speed_col] > 0)
            & (df[self.economizer_sig_col] > self.ahu_min_oa)
        )

        # AHU mech mode based on OA damper @ min OA and clg pid/vlv modulating
        df['mech_cooling_only_mode'] = (
            (df[self.heating_sig_col] == 0)
            & (df[self.cooling_sig_col] > 0)
            & (df[self.fan_vfd_speed_col] > 0)
            & (df[self.economizer_sig_col] == self.ahu_min_oa)
        )

        df = df.astype(int)

        # calc changes per hour for modes
        # https://stackoverflow.com/questions/69979832/pandas-consecutive-boolean-event-rollup-time-series

        df = df.resample('H').apply(
            lambda x: (x.eq(1) & x.shift().ne(1)).sum())

        df["fc4_flag"] = df[df.columns].gt(
            self.delta_os_max).any(1).astype(int)

        if self.troubleshoot:
            print("No troubleshooting feature yet for FC4")

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
        htg_vlv_col: str,
        fan_vfd_speed_col: str,
        troubleshoot=False
    ):
        self.mix_degf_err_thres = mix_degf_err_thres
        self.supply_degf_err_thres = supply_degf_err_thres
        self.delta_t_supply_fan = delta_t_supply_fan
        self.mat_col = mat_col
        self.sat_col = sat_col
        self.htg_vlv_col = htg_vlv_col
        self.fan_vfd_speed_col = fan_vfd_speed_col
        self.troubleshoot = troubleshoot

    # fault only active if fan is running and htg vlv is modulating
    # OS 1 is heating mode only fault
    def apply(self, df: pd.DataFrame) -> pd.DataFrame:

        df['sat_check'] = df[self.sat_col] + self.supply_degf_err_thres
        df['mat_check'] = df[self.mat_col] - \
            self.mix_degf_err_thres + self.delta_t_supply_fan

        df["fc5_flag"] = (
            (df['sat_check'] <= df['mat_check'])

            # this is to make fault only active in OS1 for htg mode only
            # and fan is running. Some control programming may use htg
            # vlv when AHU is off to prevent low limit freeze alarms
            & (df[self.htg_vlv_col] > .01)
            & (df[self.fan_vfd_speed_col] > .01)
        ).astype(int)

        if self.troubleshoot:
            print("Troubleshoot mode enabled - not removing helper columns")

        else:
            del df['mat_check']
            del df['sat_check']

        return df


class FaultConditionSix:
    """Class provides the definitions for Fault Condition 6.
        Requires an externally calculated VAV box air flow summation
        read from each VAV box air flow transmitter or supply fan AFMS
    """

    def __init__(
        self,
        airflow_err_thres: float,
        ahu_min_cfm_design: float,
        oat_degf_err_thres: float,
        rat_degf_err_thres: float,
        oat_rat_delta_min: float,
        ahu_min_oa_dpr: float,
        vav_total_flow_col: float,
        mat_col: str,
        oat_col: str,
        rat_col: str,
        fan_vfd_speed_col: str,
        economizer_sig_col: str,
        heating_sig_col: str,
        cooling_sig_col: str,
        troubleshoot=False
    ):
        self.airflow_err_thres = airflow_err_thres
        self.ahu_min_cfm_design = ahu_min_cfm_design
        self.oat_degf_err_thres = oat_degf_err_thres
        self.rat_degf_err_thres = rat_degf_err_thres
        self.oat_rat_delta_min = oat_rat_delta_min
        self.ahu_min_oa_dpr = ahu_min_oa_dpr
        self.vav_total_flow_col = vav_total_flow_col
        self.mat_col = mat_col
        self.oat_col = oat_col
        self.rat_col = rat_col
        self.fan_vfd_speed_col = fan_vfd_speed_col
        self.economizer_sig_col = economizer_sig_col
        self.heating_sig_col = heating_sig_col
        self.cooling_sig_col = cooling_sig_col
        self.troubleshoot = troubleshoot

    def apply(self, df: pd.DataFrame) -> pd.DataFrame:

        # create helper columns
        df['rat_minus_oat'] = abs(df[self.rat_col] - df[self.oat_col])
        df['percent_oa_calc'] = (df[self.mat_col] - df[self.rat_col]) / \
            (df[self.oat_col] - df[self.rat_col])

        # weed out any negative values
        df['percent_oa_calc'] = df['percent_oa_calc'].apply(
            lambda x: x if x > 0 else 0)

        df['perc_OAmin'] = (self.ahu_min_cfm_design /
                            df[self.vav_total_flow_col])  # * 100

        df['percent_oa_calc_minus_perc_OAmin'] = abs(
            df['percent_oa_calc'] - df['perc_OAmin'])

        df['fc6_flag'] = operator.or_(
            # OS 1 htg mode
            ((df['rat_minus_oat'] >= self.oat_rat_delta_min)
             & (df['percent_oa_calc_minus_perc_OAmin'] > self.airflow_err_thres))

            &  # verify ahu is running in OS 1 htg mode in min OA
            ((df[self.heating_sig_col] > 0)
             & (df[self.cooling_sig_col] == 0)
             & (df[self.fan_vfd_speed_col] > 0)
             & (df[self.economizer_sig_col] == self.ahu_min_oa_dpr)),  # OR

            # OS 4 mech clg mode
            ((df['rat_minus_oat'] >= self.oat_rat_delta_min)
             & (df['percent_oa_calc_minus_perc_OAmin'] > self.airflow_err_thres))

            &  # verify ahu is running in OS 4 clg mode in min OA
            (df[self.heating_sig_col] == 0)
            & (df[self.cooling_sig_col] > 0)
            & (df[self.fan_vfd_speed_col] > 0)
            & (df[self.economizer_sig_col] == self.ahu_min_oa_dpr)
        ).astype(int)

        if self.troubleshoot:
            print("Troubleshoot mode enabled - not removing helper columns")

        else:
            # drop helper columns
            del df['percent_oa_calc']
            del df['perc_OAmin']

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
        fan_vfd_speed_col: str,
        troubleshoot=False
    ):
        self.sat_degf_err_thres = sat_degf_err_thres
        self.sat_col = sat_col
        self.satsp_col = satsp_col
        self.htg_col = htg_col
        self.fan_vfd_speed_col = fan_vfd_speed_col
        self.troubleshoot = troubleshoot

    def apply(self, df: pd.DataFrame) -> pd.DataFrame:
        df["fc7_flag"] = (
            ((df[self.sat_col]).lt(df[self.satsp_col] - self.sat_degf_err_thres))

            # verify ahu is running in OS 1 at near full heat
            & (df[self.htg_col] > 90.)
            & (df[self.fan_vfd_speed_col] > 0)
        ).astype(int)

        if self.troubleshoot:
            print("No troubleshooting feature yet for FC4")

        return df


class FaultConditionEight:
    """Class provides the definitions for Fault Condition 8."""

    def __init__(
        self,
        delta_supply_fan: str,
        mix_err_thres: str,
        supply_err_thres: str,
        ahu_min_oa: float,
        mat_col: str,
        sat_col: str,
        economizer_sig_col: str,
        cooling_sig_col: str,
        troubleshoot=False
    ):
        self.delta_supply_fan = delta_supply_fan
        self.mix_err_thres = mix_err_thres
        self.supply_err_thres = supply_err_thres
        self.ahu_min_oa = ahu_min_oa
        self.mat_col = mat_col
        self.sat_col = sat_col
        self.economizer_sig_col = economizer_sig_col
        self.cooling_sig_col = cooling_sig_col
        self.troubleshoot = troubleshoot

    def apply(self, df: pd.DataFrame) -> pd.DataFrame:
        df['sat_fan_mat'] = abs(
            df[self.sat_col] - self.delta_supply_fan - df[self.mat_col])

        df['sat_mat_sqrted'] = np.sqrt(
            self.supply_err_thres**2 + self.mix_err_thres**2)

        df['fc8_flag'] = (
            (df['sat_fan_mat'] > df['sat_mat_sqrted'])

            # verify AHU is in OS2 only free cooling mode obly
            & (df[self.economizer_sig_col] < self.ahu_min_oa)
            & (df[self.cooling_sig_col] == 0)
        ).astype(int)

        if self.troubleshoot:
            print("Troubleshoot mode enabled - not removing helper columns")

        else:
            # drop helper columns
            del df['sat_fan_mat']
            del df['sat_mat_sqrted']

        return df


class FaultConditionNine:
    """Class provides the definitions for Fault Condition 9."""

    def __init__(
        self,
        delta_supply_fan: float,
        oat_err_thres: float,
        supply_err_thres: float,
        ahu_min_oa: float,
        satsp_col: str,
        oat_col: str,
        cooling_sig_col: str,
        economizer_sig_col: str,
        troubleshoot=False
    ):
        self.delta_supply_fan = delta_supply_fan
        self.oat_err_thres = oat_err_thres
        self.supply_err_thres = supply_err_thres
        self.ahu_min_oa = ahu_min_oa
        self.satsp_col = satsp_col
        self.oat_col = oat_col
        self.cooling_sig_col = cooling_sig_col
        self.economizer_sig_col = economizer_sig_col
        self.troubleshoot = troubleshoot

    def apply(self, df: pd.DataFrame) -> pd.DataFrame:
        df['oat_minus_oaterror'] = df[self.oat_col] - self.oat_err_thres
        df['satsp_delta_saterr'] = df[self.satsp_col] - \
            self.delta_supply_fan + self.supply_err_thres

        df['fc9_flag'] = (
            (df['oat_minus_oaterror'] > df['satsp_delta_saterr'])

            # verify AHU is in OS2 only free cooling mode obly
            & (df[self.economizer_sig_col] < self.ahu_min_oa)
            & (df[self.cooling_sig_col] == 0)
        ).astype(int)

        if self.troubleshoot:
            print("Troubleshoot mode enabled - not removing helper columns")

        else:
            # drop helper columns
            del df['oat_minus_oaterror']
            del df['satsp_delta_saterr']

        return df


class FaultConditionTen:
    """Class provides the definitions for Fault Condition 10."""

    def __init__(
        self,
        oat_err_thres: float,
        mat_err_thres: float,
        oat_col: str,
        mat_col: str,
        clg_col: str,
        economizer_sig_col: str,
        troubleshoot=False
    ):

        self.oat_err_thres = oat_err_thres
        self.mat_err_thres = mat_err_thres
        self.oat_col = oat_col
        self.mat_col = mat_col
        self.clg_col = clg_col
        self.economizer_sig_col = economizer_sig_col
        self.troubleshoot = troubleshoot

    def apply(self, df: pd.DataFrame) -> pd.DataFrame:
        df['abs_mat_minus_oat'] = abs(df[self.mat_col] - df[self.oat_col])
        df['mat_oat_sqrted'] = np.sqrt(
            self.mat_err_thres ** 2 + self.oat_err_thres ** 2)

        df['fc10_flag'] = (
            (df['abs_mat_minus_oat'] > df['mat_oat_sqrted'])

            # verify ahu is running in OS 3 clg mode in min OA
            & (df[self.clg_col] > 0)
            & (df[self.economizer_sig_col] > 90.)
        ).astype(int)

        if self.troubleshoot:
            print("Troubleshoot mode enabled - not removing helper columns")

        else:
            # drop helper columns
            del df['abs_mat_minus_oat']
            del df['mat_oat_sqrted']

        return df


class FaultConditionEleven:
    """Class provides the definitions for Fault Condition 11. Very similar to FC11."""

    def __init__(
        self,
        delta_supply_fan: float,
        oat_err_thres: float,
        supply_err_thres: float,
        satsp_col: str,
        oat_col: str,
        clg_col: str,
        economizer_sig_col: str,
        troubleshoot=False
    ):
        self.delta_supply_fan = delta_supply_fan
        self.oat_err_thres = oat_err_thres
        self.supply_err_thres = supply_err_thres
        self.satsp_col = satsp_col
        self.oat_col = oat_col
        self.clg_col = clg_col
        self.economizer_sig_col = economizer_sig_col
        self.troubleshoot = troubleshoot

    def apply(self, df: pd.DataFrame) -> pd.DataFrame:
        df['oat_plus_oaterror'] = df[self.oat_col] + self.oat_err_thres
        df['satsp_delta_saterr'] = df[self.satsp_col] - \
            self.delta_supply_fan - self.supply_err_thres

        df['fc11_flag'] = (
            (df['oat_plus_oaterror'] < df['satsp_delta_saterr'])

            # verify ahu is running in OS 3 clg mode in 100 OA
            & (df[self.clg_col] > 0)
            & (df[self.economizer_sig_col] > 90.)
        ).astype(int)

        if self.troubleshoot:
            print("Troubleshoot mode enabled - not removing helper columns")

        else:
            # drop helper columns
            del df['oat_plus_oaterror']
            del df['satsp_delta_saterr']

        return df


class FaultConditionTwelve:
    """Class provides the definitions for Fault Condition 12."""

    def __init__(
        self,
        delta_supply_fan: float,
        mix_err_thres: float,
        supply_err_thres: float,
        ahu_min_oa_dpr: float,
        sat_col: str,
        mat_col: str,
        clg_col: str,
        economizer_sig_col: str,
        troubleshoot=False
    ):
        self.delta_supply_fan = delta_supply_fan
        self.mix_err_thres = mix_err_thres
        self.supply_err_thres = supply_err_thres
        self.ahu_min_oa_dpr = ahu_min_oa_dpr
        self.sat_col = sat_col
        self.mat_col = mat_col
        self.clg_col = clg_col
        self.economizer_sig_col = economizer_sig_col
        self.troubleshoot = troubleshoot

    def apply(self, df: pd.DataFrame) -> pd.DataFrame:
        df['sat_minus_saterr_delta_supply_fan'] = df[self.sat_col] - \
            self.supply_err_thres - self.delta_supply_fan
        df['mat_plus_materr'] = df[self.mat_col] + self.mix_err_thres

        df["fc12_flag"] = operator.or_(
            # OS4 AHU state clg @ min OA
            (df['sat_minus_saterr_delta_supply_fan'] > df['mat_plus_materr'])

            & (df[self.clg_col] > 0)
            & (df[self.economizer_sig_col] == self.ahu_min_oa_dpr),  # OR
            (df['sat_minus_saterr_delta_supply_fan'] > df['mat_plus_materr'])

            # verify ahu is running in OS 3 clg mode in 100 OA
            & (df[self.clg_col] > 0)
            & (df[self.economizer_sig_col] > 90.)
        ).astype(int)

        if self.troubleshoot:
            print("Troubleshoot mode enabled - not removing helper columns")

        else:
            # drop helper columns
            del df['sat_minus_saterr_delta_supply_fan']
            del df['mat_plus_materr']

        return df


class FaultConditionThirteen:
    """Class provides the definitions for Fault Condition 13.
        Very similar to FC 13 but uses cooling valve
    """

    def __init__(
        self,
        sat_degf_err_thres: float,
        ahu_min_oa_dpr: float,
        sat_col: str,
        satsp_col: str,
        clg_col: str,
        economizer_sig_col: str,
        troubleshoot=False
    ):
        self.sat_degf_err_thres = sat_degf_err_thres
        self.ahu_min_oa_dpr = ahu_min_oa_dpr
        self.sat_col = sat_col
        self.satsp_col = satsp_col
        self.clg_col = clg_col
        self.economizer_sig_col = economizer_sig_col
        self.troubleshoot = troubleshoot

    def apply(self, df: pd.DataFrame) -> pd.DataFrame:

        df["fc13_flag"] = operator.or_(
            ((df[self.sat_col] > df[self.satsp_col]) + self.sat_degf_err_thres)
            # OS4 AHU state clg @ min OA
            & (df[self.clg_col] > 0)
            & (df[self.economizer_sig_col] == self.ahu_min_oa_dpr),  # OR
            ((df[self.sat_col] > df[self.satsp_col]) + self.sat_degf_err_thres)
            # OS3 AHU state clg @ 100% OA
            & (df[self.clg_col] > 0)
            & (df[self.economizer_sig_col] > 90.)
        ).astype(int)

        return df
