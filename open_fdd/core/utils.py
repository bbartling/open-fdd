import pandas as pd
import pandas.api.types as pdtypes
import sys


def float_int_check_err(col):
    """
    Generate an error message indicating that a column failed a float type check.

    Args:
        col (str): The name of the column.

    Returns:
        str: The error message.
    """
    err_str = " column failed with a check that the data is a float"
    return str(col) + err_str


def float_max_check_err(col):
    """
    Generate an error message indicating that a column failed a float range check.

    Args:
        col (str): The name of the column.

    Returns:
        str: The error message.
    """
    err_str = " column failed with a check that the data is a float between 0.0 and 1.0"
    return str(col) + err_str


def is_float(num):
    """
    Check if a value can be converted to a float.

    Args:
        num: The value to check.

    Returns:
        bool: True if the value can be converted to a float, False otherwise.
    """
    try:
        float(num)
        return True
    except:
        return False


def not_greater_than_one(num):
    """
    Check if a value is less than or equal to 1.0.

    Args:
        num: The value to check.

    Returns:
        bool: True if the value is less than or equal to 1.0, False otherwise.
    """
    try:
        if num <= 1.0:
            return True
    except:
        return False


def convert_to_float(df, col):
    """
    Convert a column in a DataFrame to float type if it is not already.

    Args:
        df (pd.DataFrame): The DataFrame containing the column.
        col (str): The name of the column to convert.

    Returns:
        pd.DataFrame: The updated DataFrame with the column converted to float.

    Raises:
        TypeError: If the column cannot be converted to float.
    """
    if not pdtypes.is_float_dtype(df[col]):
        try:
            df[col] = df[col].astype(float)
        except ValueError:
            raise TypeError(float_int_check_err(col))
    return df


def apply_rolling_average_if_needed(df, freq="1min", rolling_window="5min"):
    """
    Apply a rolling average to the DataFrame if the median time difference
    between consecutive timestamps is less than or equal to the specified frequency.

    Args:
        df (pd.DataFrame): The DataFrame with a datetime index.
        freq (str): The maximum allowable time difference between consecutive timestamps.
        rolling_window (str): The rolling window size for the average.

    Returns:
        pd.DataFrame: The updated DataFrame with the rolling average applied if needed.
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


def clean_nan_values(df: pd.DataFrame) -> pd.DataFrame:
    """
    Clean NaN values in a DataFrame by removing rows with NaNs and applying forward and backward fill.

    Args:
        df (pd.DataFrame): The DataFrame to clean.

    Returns:
        pd.DataFrame: The cleaned DataFrame.
    """
    for col in df.columns:
        if df[col].isnull().any():
            print(f"NaN values found in column: {col}")

            # Remove rows with any NaN values, then forward and backfill
            df = df.dropna().ffill().bfill()
            print("DataFrame has been cleaned for NaNs")
            print("and has also been forward and backfilled.")
            sys.stdout.flush()
    return df
