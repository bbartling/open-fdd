from functools import wraps
import sys
from open_fdd.core.exceptions import MissingColumnError, InvalidParameterError


class FaultConditionMixin:
    """Mixin for common fault condition functionality."""

    @staticmethod
    def _handle_errors(func):
        """Decorator to handle common errors in fault conditions."""

        @wraps(func)
        def wrapper(*args, **kwargs):
            try:
                return func(*args, **kwargs)
            except (MissingColumnError, InvalidParameterError) as e:
                print(f"Error: {e.message}")
                sys.stdout.flush()
                raise e

        return wrapper
