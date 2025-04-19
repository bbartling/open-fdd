import pandas as pd
import pytest

from open_fdd.core.base_fault import BaseFaultCondition
from open_fdd.core.exceptions import MissingColumnError


class TestFaultCondition(BaseFaultCondition):
    """Test subclass for BaseFaultCondition."""

    def _init_specific_attributes(self, dict_):
        # Initialize specific attributes
        self.test_col = dict_.get("TEST_COL", None)

        # Set required columns
        self.required_columns = [self.test_col]

        # Set documentation strings
        self.equation_string = (
            "test_flag = 1 if test_col > 0 for N consecutive values else 0 \n"
        )
        self.description_string = "Test fault condition \n"
        self.required_column_description = "Required input is the test column \n"
        self.error_string = "One or more required columns are missing or None \n"


def test_base_fault_initialization():
    # Test initialization with valid parameters
    config = {
        "TROUBLESHOOT_MODE": False,
        "ROLLING_WINDOW_SIZE": 5,
        "TEST_COL": "test_column",
    }
    fault = TestFaultCondition(config)
    assert fault.troubleshoot_mode is False
    assert fault.rolling_window_size == 5
    assert fault.test_col == "test_column"


def test_base_fault_validation():
    # Test validation of required columns
    config = {"TEST_COL": None}
    with pytest.raises(MissingColumnError):
        fault = TestFaultCondition(config)
