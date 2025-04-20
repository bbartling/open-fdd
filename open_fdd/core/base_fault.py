import sys
from typing import List

import pandas as pd

from open_fdd.core.exceptions import InvalidParameterError, MissingColumnError


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

    # def _init_specific_attributes(self, dict_):
    #     """Initialize specific attributes for the fault condition."""
    #     raise NotImplementedError("Subclasses must implement _init_specific_attributes")

    def _init_specific_attributes(self, dict_):
        # Initialize specific attributes
        self.required_columns = []
        self.range_attributes = [param for param in self.fault_params if param.range]
        required_column_map = {
            col.name: col for col in self.input_columns if col.required
        }

        for col in self.input_columns:
            value = dict_.get(col.constant_form, None)
            setattr(self, col.name, value)
            if col.required:
                self.required_columns.append(value)

        for param in self.fault_params:
            setattr(self, param.name, dict_.get(param.constant_form, None))

        self._validate_parameter_types()

        # # Validate parameter types
        # if not isinstance(self.delta_os_max, (int)):
        #     raise InvalidParameterError(
        #         f"The parameter 'delta_os_max' should be an integer data type, but got {type(self.delta_os_max).__name__}."
        #     )

        # if not isinstance(self.ahu_min_oa_dpr, float):
        #     raise InvalidParameterError(
        #         f"The parameter 'ahu_min_oa_dpr' should be a float, but got {type(self.ahu_min_oa_dpr).__name__}."
        #     )

        self.required_column_description = f"Required inputs are: {',\n'.join([f'{val.constant_form}: {val.description}' for val in required_column_map.values()])}\n"

    def _validate_required_columns(self):
        """Validate that all required columns are present."""
        if any(col is None for col in self.required_columns):
            error_message = (
                f"One or more required columns are missing or None \n"
                f"{self.equation_string}"
                f"{self.description_string}"
                f"{self.required_column_description}"
                f"{self.required_columns}"
            )
            raise MissingColumnError(error_message)
        self.required_columns = [str(col) for col in self.required_columns]
        self.mapped_columns = (
            f"Your config dictionary is mapped as: {', '.join(self.required_columns)}"
        )

    def _validate_parameter_types(self):
        """Validate that all parameters are of the correct type."""
        for param in self.fault_params:
            value = getattr(self, param.name)
            if not isinstance(value, param.type):
                raise InvalidParameterError(
                    f"The parameter '{param.name}' should be of type {param.type.__name__}, but got {type(value).__name__}."
                )
            if param.range:
                min_val, max_val = param.range
                if not (min_val <= value <= max_val):
                    raise InvalidParameterError(
                        f"The parameter '{param.name}' should be between {min_val} and {max_val}, but got {value}."
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

    def _apply_analog_checks(
        self,
        df: pd.DataFrame,
        columns_to_check: List[str],
        check_greater_than_one: bool = False,
    ):
        """Check analog outputs are floats."""
        self.check_analog_pct(df, columns_to_check, check_greater_than_one)

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

    def check_analog_pct(
        self,
        df: pd.DataFrame,
        columns_to_check: list,
        check_greater_than_one: bool = False,
    ):
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

    def get_input_column(self, name):
        """Get the value of an input column by name.

        Args:
            name: The name of the input column.

        Returns:
            The value of the input column.
        """
        return getattr(self, name, None)

    def get_param(self, name):
        """Get the value of a fault parameter by name.

        Args:
            name: The name of the parameter.

        Returns:
            The value of the parameter.
        """
        return getattr(self, name, None)
