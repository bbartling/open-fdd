
'''

import operator
import pandas as pd
import numpy as np
import pandas.api.types as pdtypes


from fault_condition import FaultCondition







class FaultConditionTen:
    """Class provides the definitions for Fault Condition 10."""

    def __init__(self, dict_):
        attributes_dict = {
            'outdoor_degf_err_thres': float,
            'mix_degf_err_thres': float,
            'oat_col': str,
            'mat_col': str,
            'cooling_sig_col': str,
            'economizer_sig_col': str,
            'troubleshoot_mode': bool,  # default False,
        }
        for attribute in attributes_dict:
            upper = attribute.upper()
            value = dict_[upper]
            self.__setattr__(upper, value)


    def apply(self, df: pd.DataFrame) -> pd.DataFrame:
        if self.troubleshoot_mode:
            print("Troubleshoot mode enabled - not removing helper columns")
            for col in df.columns:
                print(
                    "df column: ",
                    col,
                    "- max: ",
                    df[col].max(),
                    "- col type: ",
                    df[col].dtypes,
                )
        # check analog ouputs [data with units of %] are floats only
        columns_to_check = [
            self.economizer_sig_col,
            self.cooling_sig_col,
        ]

        helper = HelperUtils()

        for col in columns_to_check:
            if not pdtypes.is_float_dtype(df[col]):
                df = helper.convert_to_float(df, col)

            if df[col].max() > 1.0:
                raise TypeError(helper.float_max_check_err(col))

        df["abs_mat_minus_oat"] = abs(df[self.mat_col] - df[self.oat_col])
        df["mat_oat_sqrted"] = np.sqrt(
            self.mat_err_thres ** 2 + self.oat_err_thres ** 2
        )

        df["fc10_flag"] = (
                (df["abs_mat_minus_oat"] > df["mat_oat_sqrted"])
                # verify ahu is running in OS 3 clg mode in min OA
                & (df[self.cooling_sig_col] > 0.01)
                & (df[self.economizer_sig_col] > 0.9)
        ).astype(int)

        if self.troubleshoot_mode:
            print("Troubleshoot mode enabled - not removing helper columns")
            # drop helper columns
            del df["abs_mat_minus_oat"]
            del df["mat_oat_sqrted"]

        return df


class FaultConditionEleven:
    """Class provides the definitions for Fault Condition 11. Very similar to FC11."""

    def __init__(self, dict_):
        attributes_dict = {
            'delta_t_supply_fan': float,
            'outdoor_degf_err_thres': float,
            'supply_degf_err_thres': float,
            'sat_setpoint_col': str,
            'oat_col': str,
            'cooling_sig_col': str,
            'economizer_sig_col': str,
            'troubleshoot_mode':  bool,  # default to False,
        }
        for attribute in attributes_dict:
            upper = attribute.upper()
            value = dict_[upper]
            self.__setattr__(upper, value)

    def apply(self, df: pd.DataFrame) -> pd.DataFrame:
        if self.troubleshoot_mode:
            print("Troubleshoot mode enabled - not removing helper columns")
            for col in df.columns:
                print(
                    "df column: ",
                    col,
                    "- max: ",
                    df[col].max(),
                    "- col type: ",
                    df[col].dtypes,
                )

        # check analog ouputs [data with units of %] are floats only
        columns_to_check = [
            self.economizer_sig_col,
            self.cooling_sig_col,
        ]

        helper = HelperUtils()

        for col in columns_to_check:
            if not pdtypes.is_float_dtype(df[col]):
                df = helper.convert_to_float(df, col)

            if df[col].max() > 1.0:
                raise TypeError(helper.float_max_check_err(col))

        df["oat_plus_oaterror"] = df[self.oat_col] + self.oat_err_thres
        df["satsp_delta_saterr"] = (
                df[self.satsp_col] - self.delta_supply_fan - self.supply_err_thres
        )

        df["fc11_flag"] = (
                (df["oat_plus_oaterror"] < df["satsp_delta_saterr"])
                # verify ahu is running in OS 3 clg mode in 100 OA
                & (df[self.cooling_sig_col] > 0.01)
                & (df[self.economizer_sig_col] > 0.9)
        ).astype(int)

        if self.troubleshoot_mode:
            print("Troubleshoot mode enabled - not removing helper columns")
            # drop helper columns
            del df["oat_plus_oaterror"]
            del df["satsp_delta_saterr"]

        return df


class FaultConditionTwelve:
    """Class provides the definitions for Fault Condition 12."""

    def __init__(self, dict_):
        attributes_dict = {
            'delta_t_supply_fan': float,
            'mix_degf_err_thres': float,
            'supply_degf_err_thres': float,
            'ahu_min_oa_dpr': float,
            'sat_col': str,
            'mat_col': str,
            'cooling_sig_col': str,
            'economizer_sig_col': str,
            'troubleshoot_mode': bool  # default to False,
        }
        for attribute in attributes_dict:
            upper = attribute.upper()
            value = dict_[upper]
            self.__setattr__(upper, value)

    def apply(self, df: pd.DataFrame) -> pd.DataFrame:
        if self.troubleshoot_mode:
            print("Troubleshoot mode enabled - not removing helper columns")
            for col in df.columns:
                print(
                    "df column: ",
                    col,
                    "- max: ",
                    df[col].max(),
                    "- col type: ",
                    df[col].dtypes,
                )

        # check analog ouputs [data with units of %] are floats only
        columns_to_check = [
            self.economizer_sig_col,
            self.cooling_sig_col,
            self.ahu_min_oa_dpr
        ]

        helper = HelperUtils()

        for col in columns_to_check:
            if col == self.ahu_min_oa_dpr:
                if not helper.isfloat(col):
                    raise TypeError(helper.float_int_check_err(col))

                if not helper.isLessThanOnePointOne(col):
                    raise TypeError(helper.float_max_check_err(col))
            else:
                df = helper.convert_to_float(df, col)
                if df[col].max() > 1.0:
                    raise TypeError(helper.float_max_check_err(col))

        df["sat_minus_saterr_delta_supply_fan"] = (
                df[self.sat_col] - self.supply_err_thres - self.delta_supply_fan
        )
        df["mat_plus_materr"] = df[self.mat_col] + self.mix_err_thres

        df["fc12_flag"] = operator.or_(
            # OS4 AHU state clg @ min OA
            (df["sat_minus_saterr_delta_supply_fan"] > df["mat_plus_materr"])
            # verify AHU in OS4 mode
            & (df[self.cooling_sig_col] > 0.01)
            & (df[self.economizer_sig_col] == self.ahu_min_oa_dpr),  # OR
            (df["sat_minus_saterr_delta_supply_fan"] > df["mat_plus_materr"])
            # verify ahu is running in OS 3 clg mode in 100 OA
            & (df[self.cooling_sig_col] > 0.01) & (df[self.economizer_sig_col] > 0.9),
        ).astype(int)

        if not self.troubleshoot_mode:
            # drop helper columns
            del df["sat_minus_saterr_delta_supply_fan"]
            del df["mat_plus_materr"]

        return df


class FaultConditionThirteen:
    """Class provides the definitions for Fault Condition 13.
    Very similar to FC 13 but uses cooling valve
    """

    def __init__(self, dict_):
        attributes_dict = {
            'supply_degf_err_thres': float,
            'ahu_min_oa_dpr': float,
            'sat_col': str,
            'sat_setpoint_col': str,
            'cooling_sig_col': str,
            'economizer_sig_col': str,
            'troubleshoot_mode': bool  # should be False,
        }
        for attribute in attributes_dict:
            upper = attribute.upper()
            value = dict_[upper]
            self.__setattr__(upper, value)

    def apply(self, df: pd.DataFrame) -> pd.DataFrame:
        if self.troubleshoot_mode:
            print("Troubleshoot mode enabled - not removing helper columns")
            for col in df.columns:
                print(
                    "df column: ",
                    col,
                    "- max: ",
                    df[col].max(),
                    "- col type: ",
                    df[col].dtypes,
                )

        # check analog ouputs [data with units of %] are floats only
        columns_to_check = [
            self.economizer_sig_col,
            self.cooling_sig_col,
            self.ahu_min_oa_dpr
        ]

        helper = HelperUtils()

        for col in columns_to_check:
            if col == self.ahu_min_oa_dpr:
                if not helper.isfloat(col):
                    raise TypeError(helper.float_int_check_err(col))

                if not helper.isLessThanOnePointOne(col):
                    raise TypeError(helper.float_max_check_err(col))
            else:
                df = helper.convert_to_float(df, col)
                if df[col].max() > 1.0:
                    raise TypeError(helper.float_max_check_err(col))

        df["sat_greater_than_sp_calc"] = (
                df[self.sat_col] > df[self.satsp_col] + self.sat_degf_err_thres
        )

        df["fc13_flag"] = operator.or_(
            ((df["sat_greater_than_sp_calc"]))
            # OS4 AHU state clg @ min OA
            & (df[self.cooling_sig_col] > 0.01)
            & (df[self.economizer_sig_col] == self.ahu_min_oa_dpr),  # OR
            ((df["sat_greater_than_sp_calc"]))
            # verify ahu is running in OS 3 clg mode in 100 OA
            & (df[self.cooling_sig_col] > 0.01) & (df[self.economizer_sig_col] > 0.9),
        ).astype(int)

        if not self.troubleshoot_mode:
            # drop helper columns
            del df["sat_greater_than_sp_calc"]

        return df


class FaultConditionFourteen:
    """Class provides the definitions for Fault Condition 14."""

    def __init__(self, dict_):
        self.delta_t_supply_fan = float
        self.coil_temp_enter_err_thres = float
        self.coil_temp_leav_err_thres = float
        self.clg_coil_enter_temp_col = str
        self.clg_coil_leave_temp_col = str
        self.ahu_min_oa_dpr = float
        self.cooling_sig_col = str
        self.heating_sig_col = str
        self.economizer_sig_col = str
        self.supply_vfd_speed_col = str
        self.troubleshoot_mode = bool  # default to False

        for attribute in self.__dict__:
            upper = attribute.upper()
            value = dict_[upper]
            self.__setattr__(attribute, value)

    def apply(self, df: pd.DataFrame) -> pd.DataFrame:
        if self.troubleshoot:
            print("Troubleshoot mode enabled - not removing helper columns")
            for col in df.columns:
                print(
                    "df column: ",
                    col,
                    "- max: ",
                    df[col].max(),
                    "- col type: ",
                    df[col].dtypes,
                )

        # check analog ouputs [data with units of %] are floats only
        columns_to_check = [
            self.ahu_min_oa_dpr,
            self.cooling_sig_col,
            self.heating_sig_col,
            self.economizer_sig_col,
        ]

        helper = HelperUtils()

        for col in columns_to_check:
            if col == self.ahu_min_oa_dpr:
                if not helper.isfloat(col):
                    raise TypeError(helper.float_int_check_err(col))

                if not helper.isLessThanOnePointOne(col):
                    raise TypeError(helper.float_max_check_err(col))
            else:
                df = helper.convert_to_float(df, col)
                if df[col].max() > 1.0:
                    raise TypeError(helper.float_max_check_err(col))

        df["clg_delta_temp"] = (
                df[self.clg_coil_enter_temp_col] - df[self.clg_coil_leave_temp_col]
        )

        df["clg_delta_sqrted"] = (
                np.sqrt(
                    self.coil_temp_enter_err_thres ** 2 + self.coil_temp_leav_err_thres ** 2
                )
                + self.delta_supply_fan
        )

        df["fc14_flag"] = operator.or_(
            (df["clg_delta_temp"] >= df["clg_delta_sqrted"])
            # verify AHU is in OS2 only free cooling mode
            & (df[self.economizer_sig_col] > self.ahu_min_oa_dpr)
            & (df[self.cooling_sig_col] < 0.1),  # OR
            (df["clg_delta_temp"] >= df["clg_delta_sqrted"])
            # verify ahu is running in OS 1 at near full heat
            & (df[self.heating_sig_col] > 0.0) & (df[self.supply_vfd_speed_col] > 0.0),
        ).astype(int)

        if self.troubleshoot:
            print("Troubleshoot mode enabled - not removing helper columns")
            # drop helper columns
            del df["clg_delta_temp"]
            del df["clg_delta_sqrted"]

        return df


class FaultConditionFifteen:
    """Class provides the definitions for Fault Condition 15."""

    def __init__(
            self,
            delta_supply_fan: float,
            coil_temp_enter_err_thres: float,
            coil_temp_leav_err_thres: float,
            ahu_min_oa_dpr: float,
            htg_coil_enter_temp_col: str,
            htg_coil_leave_temp_col: str,
            cooling_sig_col: str,
            heating_sig_col: str,
            economizer_sig_col: str,
            supply_vfd_speed_col: str,
            troubleshoot: bool = False,
    ):
        self.delta_supply_fan = delta_supply_fan
        self.coil_temp_enter_err_thres = coil_temp_enter_err_thres
        self.coil_temp_leav_err_thres = coil_temp_leav_err_thres
        self.htg_coil_enter_temp_col = htg_coil_enter_temp_col
        self.htg_coil_leave_temp_col = htg_coil_leave_temp_col
        self.ahu_min_oa_dpr = ahu_min_oa_dpr
        self.cooling_sig_col = cooling_sig_col
        self.heating_sig_col = heating_sig_col
        self.economizer_sig_col = economizer_sig_col
        self.supply_vfd_speed_col = supply_vfd_speed_col
        self.troubleshoot = troubleshoot

    def apply(self, df: pd.DataFrame) -> pd.DataFrame:
        if self.troubleshoot:
            print("Troubleshoot mode enabled - not removing helper columns")
            for col in df.columns:
                print(
                    "df column: ",
                    col,
                    "- max: ",
                    df[col].max(),
                    "- col type: ",
                    df[col].dtypes,
                )

        # check analog ouputs [data with units of %] are floats only
        columns_to_check = [
            self.ahu_min_oa_dpr,
            self.cooling_sig_col,
            self.heating_sig_col,
            self.economizer_sig_col,
        ]

        helper = HelperUtils()

        for col in columns_to_check:
            if col == self.ahu_min_oa_dpr:
                if not helper.isfloat(col):
                    raise TypeError(helper.float_int_check_err(col))

                if not helper.isLessThanOnePointOne(col):
                    raise TypeError(helper.float_max_check_err(col))
            else:
                df = helper.convert_to_float(df, col)
                if df[col].max() > 1.0:
                    raise TypeError(helper.float_max_check_err(col))

        df["htg_delta_temp"] = (
                df[self.htg_coil_enter_temp_col] - df[self.htg_coil_leave_temp_col]
        )

        df["htg_delta_sqrted"] = (
                np.sqrt(
                    self.coil_temp_enter_err_thres ** 2 + self.coil_temp_leav_err_thres ** 2
                )
                + self.delta_supply_fan
        )

        df["fc15_flag"] = (
                (
                        (df["htg_delta_temp"] >= df["htg_delta_sqrted"])
                        # verify AHU is in OS2 only free cooling mode
                        & (df[self.economizer_sig_col] > self.ahu_min_oa_dpr)
                        & (df[self.cooling_sig_col] < 0.1)
                )  # OR
                | (
                        (df["htg_delta_temp"] >= df["htg_delta_sqrted"])
                        # OS4 AHU state clg @ min OA
                        & (df[self.cooling_sig_col] > 0.01)
                        & (df[self.economizer_sig_col] == self.ahu_min_oa_dpr)
                )  # OR
                | (
                        (df["htg_delta_temp"] >= df["htg_delta_sqrted"])
                        # verify ahu is running in OS 3 clg mode in 100 OA
                        & (df[self.cooling_sig_col] > 0.01)
                        & (df[self.economizer_sig_col] > 0.9)
                )
        ).astype(int)

        if self.troubleshoot:
            print("Troubleshoot mode enabled - not removing helper columns")
            # drop helper columns
            del df["htg_delta_temp"]
            del df["htg_delta_sqrted"]

        return df

        
'''