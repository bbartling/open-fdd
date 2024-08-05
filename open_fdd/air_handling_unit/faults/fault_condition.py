import pandas.api.types as pdtypes
from open_fdd.air_handling_unit.faults.helper_utils import HelperUtils
import sys


class FaultCondition:
    
    """Parent class for Fault Conditions. Methods are inherited to all children."""

    def set_attributes(self, dict_):
        """Passes dictionary into initialization of class instance, then uses the attributes called out below in
        attributes_dict to set only the attributes that match from dict_.

        :param dict_: dictionary of all possible class attributes (loaded from config file)
        """
        for attribute in self.__dict__:
            upper = attribute.upper()
            value = dict_[upper]
            self.__setattr__(attribute, value)

    def troubleshoot_cols(self, df):
        """print troubleshoot columns mapping

        :param df:
        :return:
        """
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
            sys.stdout.flush()

    def check_analog_pct(self, df, columns):
        """check analog outputs [data with units of %] are floats only

        :param columns:
        :return:
        """
        helper = HelperUtils()
        for col in columns:
            if not pdtypes.is_float_dtype(df[col]):
                df = helper.convert_to_float(df, col)
            if df[col].max() > 1.0:
                raise TypeError(helper.float_max_check_err(col))


