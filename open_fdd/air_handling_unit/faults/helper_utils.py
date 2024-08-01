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
    

    def apply_rolling_average_if_needed(self, df, freq="1T", rolling_window="5T"):
        """Apply rolling average if time difference between consecutive timestamps is not greater than the specified frequency."""
        time_diff = df.index.to_series().diff().iloc[1:]
        max_diff = time_diff.max()

        if max_diff > pd.Timedelta(minutes=5):
            print(f"Warning: Maximum time difference between consecutive timestamps is {max_diff}.")
            print("SKIPPING 5 MINUTE ROLLING AVERAGE COMPUTATION OF DATA")
        else:
            df = df.rolling(rolling_window).mean()
        return df