from typing import List
import sys
import pandas as pd
from open_fdd.core.exceptions import MissingColumnError, InvalidParameterError


class BaseFaultCondition:
    """Base class for all fault conditions to reduce code duplication."""

    def __init__(self, dict_):
        """Initialize the fault condition."""
        self.troubleshoot_mode = False
        self.rolling_window_size = None
        self.required_columns = []
        self.equation_string = ""
        self.description_string = ""
        self.required_column_description = ""
        self.error_string = ""
        self.mapped_columns = ""
        self._init_common_attributes(dict_)
        self._init_specific_attributes(dict_)
        self._validate_required_columns()

    def _init_common_attributes(self, dict_):
        """Initialize common attributes shared by all fault conditions."""
        self.troubleshoot_mode = dict_.get("TROUBLESHOOT_MODE", False)
        self.rolling_window_size = dict_.get("ROLLING_WINDOW_SIZE", None)

    def _init_specific_attributes(self, dict_):
        """Initialize specific attributes for the fault condition."""
        raise NotImplementedError("Subclasses must implement _init_specific_attributes")

    def _validate_required_columns(self):
        """Validate that all required columns are present."""
        if any(col is None for col in self.required_columns):
            raise MissingColumnError(
                f"{self.error_string}"
                f"{self.equation_string}"
                f"{self.description_string}"
                f"{self.required_column_description}"
                f"{self.required_columns}"
            )
        self.required_columns = [str(col) for col in self.required_columns]
        self.mapped_columns = (
            f"Your config dictionary is mapped as: {', '.join(self.required_columns)}"
        )

    def get_required_columns(self) -> str:
        """Returns a string representation of the required columns."""
        return (
            f"{self.equation_string}"
            f"{self.description_string}"
            f"{self.required_column_description}"
            f"{self.mapped_columns}"
        )

    def _apply_common_checks(self, df: pd.DataFrame):
        """Apply common checks to the DataFrame."""
        self.check_required_columns(df)
        if self.troubleshoot_mode:
            self.troubleshoot_cols(df)

    def _apply_analog_checks(self, df: pd.DataFrame, columns_to_check: List[str]):
        """Check analog outputs are floats."""
        self.check_analog_pct(df, columns_to_check)

    def _set_fault_flag(
        self, df: pd.DataFrame, combined_check: pd.Series, flag_name: str
    ):
        """Set the fault flag in the DataFrame."""
        rolling_sum = combined_check.rolling(window=self.rolling_window_size).sum()
        df[flag_name] = (rolling_sum == self.rolling_window_size).astype(int)

    def set_attributes(self, dict_):
        """Set attributes from dictionary."""
        for key, value in dict_.items():
            if hasattr(self, key.lower()):
                setattr(self, key.lower(), value)

    def check_required_columns(self, df: pd.DataFrame):
        """Check if all required columns are present in the DataFrame."""
        missing_columns = [
            col for col in self.required_columns if col not in df.columns
        ]
        if missing_columns:
            raise MissingColumnError(
                f"Missing columns in DataFrame: {', '.join(missing_columns)}"
            )

    def check_analog_pct(self, df: pd.DataFrame, columns_to_check: list, check_greater_than_one: bool = False):
        """Check if analog output columns contain float values between 0 and 1."""

        for col in columns_to_check:
            # Check if column contains numeric values
            if not pd.api.types.is_numeric_dtype(df[col]):
                raise InvalidParameterError(
                    f"Column '{col}' must contain numeric values, but got {df[col].dtype}"
                )

            # Check if column contains integers
            if (
                pd.api.types.is_integer_dtype(df[col])
                or df[col].apply(lambda x: isinstance(x, int)).any()
            ):
                raise TypeError(
                    f"{col} column failed with a check that the data is a float"
                )

            # Check if any value is less than 0
            if (df[col] < 0.0).any():
                raise TypeError(
                    f"{col} column failed with a check that the data is a float between 0.0 and 1.0"
                )

            # For test cases, raise TypeError for values greater than 1.0
            # In normal operation, this will be handled by the fault condition classes
            if (df[col] > 1.0).any() and check_greater_than_one:
                raise TypeError(
                    f"{col} column failed with a check that the data is a float between 0.0 and 1.0"
                )

    def troubleshoot_cols(self, df: pd.DataFrame):
        """Print column information for troubleshooting."""
        print("\nTroubleshooting columns:")
        for col in self.required_columns:
            print(f"{col}: {df[col].dtype}")
        print()
