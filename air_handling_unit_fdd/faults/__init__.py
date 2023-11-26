import operator
import pandas as pd
import numpy as np
import pandas.api.types as pdtypes


class HelperUtils:
    def float_int_check_err(self, col):
        err_str = " column failed with a check that the data is a float"
        return str(col) + err_str

    def float_max_check_err(self, col):
        err_str = (
            " column failed with a check that the data is a float between 0.0 and 1.0"
        )
        return str(col) + err_str

    def isfloat(self, num):
        try:
            float(num)
            return True
        except:
            return False

    def isLessThanOnePointOne(self, num):
        try:
            if num <= 1.0:
                return True
        except:
            return False

    def convert_to_float(self, df, col):
        if not pdtypes.is_float_dtype(df[col]):
            try:
                df[col] = df[col].astype(float)
            except ValueError:
                raise TypeError(self.float_int_check_err(col))
        return df


class FaultConditionOne:
    """Class provides the definitions for Fault Condition 1."""

    def __init__(self, dict_):
        """Passes dictionary into initialization of class instance, then uses the attributes called out below in
        attributes_dict to set only the attributes that match from dict_.

        :param dict_: dictionary of all possible class attributes (loaded from config file)
        """
        attributes_dict = {
            'vfd_speed_percent_err_thres': float,
            'vfd_speed_percent_max': float,
            'duct_static_inches_err_thres': float,
            'duct_static_col': str,
            'supply_vfd_speed_col': str,
            'duct_static_setpoint_col': str,
            'troubleshoot_mode': bool,  # default should be False
        }
        for attribute in attributes_dict:
            upper = attribute.upper()
            value = dict_[upper]
            self.__setattr__(upper, value)

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
        columns_to_check = [self.supply_vfd_speed_col]

        helper = HelperUtils()

        for col in columns_to_check:
            if not pdtypes.is_float_dtype(df[col]):
                df = helper.convert_to_float(df, col)

            if df[col].max() > 1.0:
                raise TypeError(helper.float_max_check_err(col))

        df["static_check_"] = (
                df[self.duct_static_col]
                < df[self.duct_static_setpoint_col] - self.duct_static_inches_err_thres
        )
        df["fan_check_"] = (
                df[self.supply_vfd_speed_col]
                >= self.vfd_speed_percent_max - self.vfd_speed_percent_err_thres
        )

        df["fc1_flag"] = (df["static_check_"] & df["fan_check_"]).astype(int)

        if self.troubleshoot:
            print("Troubleshoot mode enabled - not removing helper columns")
            del df["static_check_"]
            del df["fan_check_"]

        return df


class FaultConditionTwo:
    """Class provides the definitions for Fault Condition 2."""

    def __init__(self, dict_):
        attributes_dict = {
            'mix_degf_err_thres': float,
            'return_degf_err_thres': float,
            'outdoor_degf_err_thres': float,
            'mat_col': str,
            'rat_col': str,
            'oat_col': str,
            'supply_vfd_speed_col': str,
            'troubleshoot_mode': bool,  # default to False,
        }
        for attribute in attributes_dict:
            upper = attribute.upper()
            value = dict_[upper]
            self.__setattr__(upper, value)

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
        columns_to_check = [self.supply_vfd_speed_col]

        helper = HelperUtils()

        for col in columns_to_check:
            if not pdtypes.is_float_dtype(df[col]):
                df = helper.convert_to_float(df, col)

            if df[col].max() > 1.0:
                raise TypeError(helper.float_max_check_err(col))

        df["mat_check"] = df[self.mat_col] + self.mix_degf_err_thres
        df["temp_min_check"] = np.minimum(
            df[self.rat_col] - self.return_degf_err_thres,
            df[self.oat_col] - self.outdoor_degf_err_thres,
        )

        df["fc2_flag"] = (
                (df["mat_check"] < df["temp_min_check"])
                # this fault is supposed to contain OS state 5
                # confirm with G36 fault author adding in fan status okay
                & (df[self.supply_vfd_speed_col] > 0.01)
        ).astype(int)

        if self.troubleshoot:
            print("Troubleshoot mode enabled - not removing helper columns")
            del df["mat_check"]
            del df["temp_min_check"]

        return df


class FaultConditionThree:
    """Class provides the definitions for Fault Condition 3."""

    def __init__(self, dict_):
        attributes_dict = {
            'mix_degf_err_thres': float,
            'return_degf_err_thres': float,
            'outdoor_degf_err_thres': float,
            'mat_col': str,
            'rat_col': str,
            'oat_col': str,
            'supply_vfd_speed_col': str,
            'troubleshoot_mode': bool  # default to False,
        }
        for attribute in attributes_dict:
            upper = attribute.upper()
            value = dict_[upper]
            self.__setattr__(upper, value)

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
        columns_to_check = [self.supply_vfd_speed_col]

        helper = HelperUtils()

        for col in columns_to_check:
            if not pdtypes.is_float_dtype(df[col]):
                df = helper.convert_to_float(df, col)

            if df[col].max() > 1.0:
                raise TypeError(helper.float_max_check_err(col))

        df["mat_check"] = df[self.mat_col] - self.mix_degf_err_thres
        df["temp_min_check"] = np.maximum(
            df[self.rat_col] + self.return_degf_err_thres,
            df[self.oat_col] + self.outdoor_degf_err_thres,
        )

        df["fc3_flag"] = (
                (df["mat_check"] > df["temp_min_check"])
                # this fault is supposed to contain OS state 5
                # confirm with G36 fault author adding in fan status okay
                & (df[self.supply_vfd_speed_col] > 0.01)
        ).astype(int)

        if self.troubleshoot:
            print("Troubleshoot mode enabled - not removing helper columns")
            del df["mat_check"]
            del df["temp_min_check"]

        return df


class FaultConditionFour:
    """Class provides the definitions for Fault Condition 4."""

    def __init__(self, dict_):
        attributes_dict = {
            'delta_os_max': float,
            'ahu_min_oa_dpr': float,
            'economizer_sig_col': str,
            'heating_sig_col': str,
            'cooling_sig_col': str,
            'supply_vfd_speed_col': str,
            'troubleshoot_mode': bool  # default should be False
        }
        for attribute in attributes_dict:
            upper = attribute.upper()
            value = dict_[upper]
            self.__setattr__(upper, value)

    # adds in these boolean columns to the dataframe
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
                    "- Pandas is float check: ",
                    pdtypes.is_float_dtype(df[col])
                )
        # check analog ouputs [data with units of %] are floats only
        columns_to_check = [
            self.economizer_sig_col,
            self.heating_sig_col,
            self.cooling_sig_col,
            self.supply_vfd_speed_col,
            self.ahu_min_oa_dpr,
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

        print("Compiling data in Pandas this one takes a while to run...")

        # AHU htg only mode based on OA damper @ min oa and only htg pid/vlv modulating
        df["heating_mode"] = (
                (df[self.heating_sig_col] > 0)
                & (df[self.cooling_sig_col] == 0)
                & (df[self.supply_vfd_speed_col] > 0)
                & (df[self.economizer_sig_col] == self.ahu_min_oa_dpr)
        )

        # AHU econ only mode based on OA damper modulating and clg htg = zero
        df["econ_only_cooling_mode"] = (
                (df[self.heating_sig_col] == 0)
                & (df[self.cooling_sig_col] == 0)
                & (df[self.supply_vfd_speed_col] > 0)
                & (df[self.economizer_sig_col] > self.ahu_min_oa_dpr)
        )

        # AHU econ+mech clg mode based on OA damper modulating for cooling and clg pid/vlv modulating
        df["econ_plus_mech_cooling_mode"] = (
                (df[self.heating_sig_col] == 0)
                & (df[self.cooling_sig_col] > 0)
                & (df[self.supply_vfd_speed_col] > 0)
                & (df[self.economizer_sig_col] > self.ahu_min_oa_dpr)
        )

        # AHU mech mode based on OA damper @ min OA and clg pid/vlv modulating
        df["mech_cooling_only_mode"] = (
                (df[self.heating_sig_col] == 0)
                & (df[self.cooling_sig_col] > 0)
                & (df[self.supply_vfd_speed_col] > 0)
                & (df[self.economizer_sig_col] == self.ahu_min_oa_dpr)
        )

        df = df.astype(int)
        df = df.resample("H").apply(lambda x: (x.eq(1) & x.shift().ne(1)).sum())

        df["fc4_flag"] = df[df.columns].gt(self.delta_os_max).any(1).astype(int)
        return df


class FaultConditionFive:
    """Class provides the definitions for Fault Condition 5."""

    def __init__(self, dict_):
        attributes_dict = {
            'mix_degf_err_thres': float,
            'supply_degf_err_thres': float,
            'delta_t_supply_fan': float,
            'mat_col': str,
            'sat_col': str,
            'heating_sig_col': str,
            'supply_vfd_speed_col': str,
            'troubleshoot_mode':  bool  # default should be False
        }
        for attribute in attributes_dict:
            upper = attribute.upper()
            value = dict_[upper]
            self.__setattr__(upper, value)

    # fault only active if fan is running and htg vlv is modulating
    # OS 1 is heating mode only fault
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
        columns_to_check = [self.supply_vfd_speed_col, self.heating_sig_col]

        helper = HelperUtils()

        for col in columns_to_check:
            if not pdtypes.is_float_dtype(df[col]):
                df = helper.convert_to_float(df, col)

            if df[col].max() > 1.0:
                raise TypeError(helper.float_max_check_err(col))

        df["sat_check"] = df[self.sat_col] + self.supply_degf_err_thres
        df["mat_check"] = (
                df[self.mat_col] - self.mix_degf_err_thres + self.delta_t_supply_fan
        )

        df["fc5_flag"] = (
                (df["sat_check"] <= df["mat_check"])
                # this is to make fault only active in OS1 for htg mode only
                # and fan is running. Some control programming may use htg
                # vlv when AHU is off to prevent low limit freeze alarms
                & (df[self.heating_sig_col] > 0.01)
                & (df[self.supply_vfd_speed_col] > 0.01)
        ).astype(int)

        if self.troubleshoot:
            print("Troubleshoot mode enabled - not removing helper columns")
            del df["mat_check"]
            del df["sat_check"]

        return df


class FaultConditionSix:
    """Class provides the definitions for Fault Condition 6.
    Requires an externally calculated VAV box air flow summation
    read from each VAV box air flow transmitter or supply fan AFMS
    """

    def __init__(self, dict_):
        attributes_dict = {
            'airflow_err_thres': float,
            'ahu_min_oa_cfm_design': float,
            'outdoor_degf_err_thres': float,
            'return_degf_err_thres': float,
            'oat_rat_delta_min': float,
            'ahu_min_oa_dpr': float,
            'supply_fan_air_volume_col': float,  # this appears to be a proxy for external VAV cfm summation. See class
            # def. Default config dict passes this as a string.
            'mat_col': str,
            'oat_col': str,
            'rat_col': str,
            'supply_vfd_speed_col': str,
            'economizer_sig_col': str,
            'heating_sig_col': str,
            'cooling_sig_col': str,
            'troubleshoot_mode': bool  # default should be False,
        }
        for attribute in attributes_dict:
            upper = attribute.upper()
            value = dict_[upper]
            self.__setattr__(upper, value)

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
            self.supply_vfd_speed_col,
            self.economizer_sig_col,
            self.heating_sig_col,
            self.cooling_sig_col,
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

        # create helper columns
        df["rat_minus_oat"] = abs(df[self.rat_col] - df[self.oat_col])
        df["percent_oa_calc"] = (df[self.mat_col] - df[self.rat_col]) / (
                df[self.oat_col] - df[self.rat_col]
        )

        # weed out any negative values
        df["percent_oa_calc"] = df["percent_oa_calc"].apply(lambda x: x if x > 0 else 0)

        df["perc_OAmin"] = (
                self.ahu_min_cfm_design / df[self.vav_total_flow_col]
        )  # * 100

        df["percent_oa_calc_minus_perc_OAmin"] = abs(
            df["percent_oa_calc"] - df["perc_OAmin"]
        )

        df["fc6_flag"] = operator.or_(
            # OS 1 htg mode
            (
                    (df["rat_minus_oat"] >= self.oat_rat_delta_min)
                    & (df["percent_oa_calc_minus_perc_OAmin"] > self.airflow_err_thres)
            )
            # verify ahu is running in OS 1 htg mode in min OA
            & (
                    (df[self.heating_sig_col] > 0.0) & (df[self.supply_vfd_speed_col] > 0.0)
            ),  # OR
            # OS 4 mech clg mode
            (
                    (df["rat_minus_oat"] >= self.oat_rat_delta_min)
                    & (df["percent_oa_calc_minus_perc_OAmin"] > self.airflow_err_thres)
            )
            # verify ahu is running in OS 4 clg mode in min OA
            & (df[self.heating_sig_col] == 0.0)
            & (df[self.cooling_sig_col] > 0.0)
            & (df[self.supply_vfd_speed_col] > 0.0)
            & (df[self.economizer_sig_col] == self.ahu_min_oa_dpr),
        ).astype(int)

        return df


class FaultConditionSeven:
    """Class provides the definitions for Fault Condition 7.
    Very similar to FC 13 but uses heating valve
    """

    def __init__(self, dict_):
        attributes_dict = {
            'supply_degf_err_thres': float,
            'sat_col': str,
            'sat_setpoint_col': str,
            'heating_sig_col': str,
            'supply_vfd_speed_col': str,
            'troubleshoot_mode': bool,  # should default to False
        }
        for attribute in attributes_dict:
            upper = attribute.upper()
            value = dict_[upper]
            self.__setattr__(upper, value)

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
        columns_to_check = [self.supply_vfd_speed_col, self.heating_sig_col]

        helper = HelperUtils()

        for col in columns_to_check:
            if not pdtypes.is_float_dtype(df[col]):
                df = helper.convert_to_float(df, col)

            if df[col].max() > 1.0:
                raise TypeError(helper.float_max_check_err(col))

        df["fc7_flag"] = (
                (df[self.sat_col] < df[self.satsp_col] - self.sat_degf_err_thres)
                # verify ahu is running in OS 1 at near full heat
                & (df[self.heating_sig_col] > 0.9)
                & (df[self.supply_vfd_speed_col] > 0)
        ).astype(int)

        if self.troubleshoot:
            print("No troubleshooting feature yet for FC4")

        return df


class FaultConditionEight:
    """Class provides the definitions for Fault Condition 8."""

    def __init__(self, dict_):
        attributes_dict = {
            'delta_t_supply_fan': float,
            'mix_degf_err_thres': float,
            'supply_degf_err_thres': float,
            'ahu_min_oa_dpr': float,
            'mat_col': str,
            'sat_col': str,
            'economizer_sig_col': str,
            'cooling_sig_col': str,
            'troubleshoot_mode': bool  # default should be False
        }
        for attribute in attributes_dict:
            upper = attribute.upper()
            value = dict_[upper]
            self.__setattr__(upper, value)

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

        df["sat_fan_mat"] = abs(
            df[self.sat_col] - self.delta_supply_fan - df[self.mat_col]
        )

        df["sat_mat_sqrted"] = np.sqrt(
            self.supply_err_thres ** 2 + self.mix_err_thres ** 2
        )

        df["fc8_flag"] = (
                (df["sat_fan_mat"] > df["sat_mat_sqrted"])
                # verify AHU is in OS2 only free cooling mode
                & (df[self.economizer_sig_col] > self.ahu_min_oa_dpr)
                & (df[self.cooling_sig_col] < 0.1)
        ).astype(int)

        if self.troubleshoot:
            print("Troubleshoot mode enabled - not removing helper columns")
            # drop helper columns
            del df["sat_fan_mat"]
            del df["sat_mat_sqrted"]

        return df


class FaultConditionNine:
    """Class provides the definitions for Fault Condition 9."""

    def __init__(self, dict_):
        attributes_dict = {
            'delta_t_supply_fan': float,
            'outdoor_degf_err_thres': float,
            'supply_degf_err_thres': float,
            'ahu_min_oa_dpr': float,
            'sat_setpoint_col': str,
            'oat_col': str,
            'cooling_sig_col': str,
            'economizer_sig_col': str,
            'troubleshoot_mode': bool  # should default to False,
        }
        for attribute in attributes_dict:
            upper = attribute.upper()
            value = dict_[upper]
            self.__setattr__(upper, value)

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

        df["oat_minus_oaterror"] = df[self.oat_col] - self.oat_err_thres
        df["satsp_delta_saterr"] = (
                df[self.satsp_col] - self.delta_supply_fan + self.supply_err_thres
        )

        df["fc9_flag"] = (
                (df["oat_minus_oaterror"] > df["satsp_delta_saterr"])
                # verify AHU is in OS2 only free cooling mode
                & (df[self.economizer_sig_col] > self.ahu_min_oa_dpr)
                & (df[self.cooling_sig_col] < 0.1)
        ).astype(int)

        if self.troubleshoot:
            print("Troubleshoot mode enabled - not removing helper columns")
            # drop helper columns
            del df["oat_minus_oaterror"]
            del df["satsp_delta_saterr"]

        return df


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

        if self.troubleshoot:
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

        if self.troubleshoot:
            print("Troubleshoot mode enabled - not removing helper columns")
            # drop helper columns
            del df["oat_plus_oaterror"]
            del df["satsp_delta_saterr"]

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
            cooling_sig_col: str,
            economizer_sig_col: str,
            troubleshoot: bool = False,
    ):
        self.delta_supply_fan = delta_supply_fan
        self.mix_err_thres = mix_err_thres
        self.supply_err_thres = supply_err_thres
        self.ahu_min_oa_dpr = ahu_min_oa_dpr
        self.sat_col = sat_col
        self.mat_col = mat_col
        self.cooling_sig_col = cooling_sig_col
        self.economizer_sig_col = economizer_sig_col
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

        if not self.troubleshoot:
            # drop helper columns
            del df["sat_minus_saterr_delta_supply_fan"]
            del df["mat_plus_materr"]

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
            cooling_sig_col: str,
            economizer_sig_col: str,
            troubleshoot: bool = False,
    ):
        self.sat_degf_err_thres = sat_degf_err_thres
        self.ahu_min_oa_dpr = ahu_min_oa_dpr
        self.sat_col = sat_col
        self.satsp_col = satsp_col
        self.cooling_sig_col = cooling_sig_col
        self.economizer_sig_col = economizer_sig_col
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

        if not self.troubleshoot:
            # drop helper columns
            del df["sat_greater_than_sp_calc"]

        return df


class FaultConditionFourteen:
    """Class provides the definitions for Fault Condition 14."""

    def __init__(
            self,
            delta_supply_fan: float,
            coil_temp_enter_err_thres: float,
            coil_temp_leav_err_thres: float,
            ahu_min_oa_dpr: float,
            clg_coil_enter_temp_col: str,
            clg_coil_leave_temp_col: str,
            cooling_sig_col: str,
            heating_sig_col: str,
            economizer_sig_col: str,
            supply_vfd_speed_col: str,
            troubleshoot: bool = False,
    ):
        self.delta_supply_fan = delta_supply_fan
        self.coil_temp_enter_err_thres = coil_temp_enter_err_thres
        self.coil_temp_leav_err_thres = coil_temp_leav_err_thres
        self.clg_coil_enter_temp_col = clg_coil_enter_temp_col
        self.clg_coil_leave_temp_col = clg_coil_leave_temp_col
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
