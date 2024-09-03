import pandas as pd
import pandas.api.types as pdtypes
import sys


class SharedUtils:
    @staticmethod
    def float_int_check_err(col):
        err_str = " column failed with a check that the data is a float"
        return str(col) + err_str

    @staticmethod
    def float_max_check_err(col):
        err_str = (
            " column failed with a check that the data is a float between 0.0 and 1.0"
        )
        return str(col) + err_str

    @staticmethod
    def isfloat(num):
        try:
            float(num)
            return True
        except:
            return False

    @staticmethod
    def isLessThanOnePointOne(num):
        try:
            if num <= 1.0:
                return True
        except:
            return False

    @staticmethod
    def convert_to_float(df, col):
        if not pdtypes.is_float_dtype(df[col]):
            try:
                df[col] = df[col].astype(float)
            except ValueError:
                raise TypeError(SharedUtils.float_int_check_err(col))
        return df

    @staticmethod
    def apply_rolling_average_if_needed(df, freq="1min", rolling_window="5min"):
        """Apply rolling average if time difference between consecutive
        timestamps is not greater than the specified frequency.
        """

        print(
            "Warning: If data has a one minute or less sampling \n"
            "frequency a rolling average will be automatically applied"
        )

        sys.stdout.flush()

        time_diff = df.index.to_series().diff().iloc[1:]

        # Calculate median time difference to avoid being affected by outliers
        median_diff = time_diff.median()

        print(
            f"Warning: Median time difference between consecutive timestamps is {median_diff}."
        )
        sys.stdout.flush()

        if median_diff > pd.Timedelta(freq):
            print(f"Warning: Skipping any rolling averaging...")
            sys.stdout.flush()

        else:
            df = df.rolling(rolling_window).mean()
            print(
                f"Warning: A {rolling_window} rolling average has been applied to the data."
            )
            sys.stdout.flush()
        return df

    @staticmethod
    def clean_nan_values(df: pd.DataFrame) -> pd.DataFrame:
        for col in df.columns:
            if df[col].isnull().any():
                print(f"NaN values found in column: {col}")

                # Remove rows with any NaN values, then forward and backfill
                df = df.dropna().ffill().bfill()
                print("DataFrame has been cleaned for NaNs")
                print("and has also been forward and backfilled.")
                sys.stdout.flush()
        return df
