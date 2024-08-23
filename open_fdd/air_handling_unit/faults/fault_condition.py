import pandas as pd
import pandas.api.types as pdtypes
from open_fdd.air_handling_unit.faults.helper_utils import HelperUtils
import sys


class MissingColumnError(Exception):
    """Custom exception raised when a required column is missing or None."""

    def __init__(self, message):
        self.message = message
        super().__init__(self.message)


class FaultCondition:
    """Parent class for Fault Conditions. Methods are inherited to all children."""

    def __init__(self):
        self.required_columns = []

    def set_attributes(self, dict_):
        """Passes dictionary into initialization of class instance"""
        for attribute in self.__dict__.keys():
            upper = attribute.upper()
            if upper in dict_:
                value = dict_[upper]
                self.__setattr__(attribute, value)

    def check_required_columns(self, df: pd.DataFrame):
        """Checks if required columns are present in the DataFrame."""
        missing_columns = [
            col for col in self.required_columns if col is None or col not in df.columns
        ]

        if missing_columns:
            raise MissingColumnError(f"Missing required columns: {missing_columns}")

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
