from functools import wraps
import sys
from open_fdd.core.exceptions import MissingColumnError
from open_fdd.core.exceptions import InvalidParameterError


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
                MissingColumnError,
                InvalidParameterError,
                MissingColumnError,
                InvalidParameterError,
            ) as e:
                print(f"Error: {e.message}")
                sys.stdout.flush()
                # Raise a new instance of the appropriate exception type
                # This allows pytest.raises to catch it
                if isinstance(e, MissingColumnError):
                    raise MissingColumnError(e.message)
                elif isinstance(e, InvalidParameterError):
                    raise InvalidParameterError(e.message)
                else:
                    raise e

        return wrapper
