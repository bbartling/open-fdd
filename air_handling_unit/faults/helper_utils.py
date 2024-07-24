import pandas as pd
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