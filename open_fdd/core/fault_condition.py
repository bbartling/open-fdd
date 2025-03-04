import pandas as pd
from open_fdd.core.exceptions import InvalidParameterError


class FaultCondition:
    """Base class for all fault conditions."""

    def __init__(self):
        """Initialize the fault condition."""
        self.troubleshoot_mode = False
        self.rolling_window_size = None
        self.required_columns = []
        self.equation_string = ""
        self.description_string = ""
        self.required_column_description = ""
        self.error_string = ""
        self.mapped_columns = ""

    def set_attributes(self, dict_):
        """Set attributes from dictionary."""
        for key, value in dict_.items():
            if hasattr(self, key.lower()):
                setattr(self, key.lower(), value)

    def check_required_columns(self, df: pd.DataFrame):
        """Check if all required columns are present in the DataFrame."""
        missing_columns = [col for col in self.required_columns if col not in df.columns]
        if missing_columns:
            raise MissingColumnError(
                f"Missing columns in DataFrame: {', '.join(missing_columns)}"
            )

    def check_analog_pct(self, df: pd.DataFrame, columns_to_check: list):
        """Check if analog output columns contain float values."""
        for col in columns_to_check:
            if not pd.api.types.is_numeric_dtype(df[col]):
                raise InvalidParameterError(
                    f"Column '{col}' must contain numeric values, but got {df[col].dtype}"
                )

    def troubleshoot_cols(self, df: pd.DataFrame):
        """Print column information for troubleshooting."""
        print("\nTroubleshooting columns:")
        for col in self.required_columns:
            print(f"{col}: {df[col].dtype}")
        print() 