from typing import List
import pandas as pd
from open_fdd.core.fault_condition import FaultCondition
from open_fdd.core.exceptions import MissingColumnError, InvalidParameterError


class BaseFaultCondition(FaultCondition):
    """Base class for all fault conditions to reduce code duplication."""

    def __init__(self, dict_):
        super().__init__()
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
