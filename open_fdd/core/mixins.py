from functools import wraps
import sys
from open_fdd.core.exceptions import MissingColumnError as CoreMissingColumnError
from open_fdd.core.exceptions import InvalidParameterError as CoreInvalidParameterError
from open_fdd.air_handling_unit.faults.fault_condition import (
    MissingColumnError as FaultMissingColumnError,
)
from open_fdd.air_handling_unit.faults.fault_condition import (
    InvalidParameterError as FaultInvalidParameterError,
)


class FaultConditionMixin:
    """Mixin for common fault condition functionality."""

    @staticmethod
    def _handle_errors(func):
        """Decorator to handle common errors in fault conditions."""

        @wraps(func)
        def wrapper(*args, **kwargs):
            try:
                return func(*args, **kwargs)
            except (
                CoreMissingColumnError,
                CoreInvalidParameterError,
                FaultMissingColumnError,
                FaultInvalidParameterError,
            ) as e:
                print(f"Error: {e.message}")
                sys.stdout.flush()
                # Raise a new instance of the appropriate exception type
                # This allows pytest.raises to catch it
                if isinstance(e, CoreMissingColumnError):
                    raise FaultMissingColumnError(e.message)
                elif isinstance(e, CoreInvalidParameterError):
                    raise FaultInvalidParameterError(e.message)
                else:
                    raise e

        return wrapper
