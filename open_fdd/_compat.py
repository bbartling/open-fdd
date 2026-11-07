"""Compatibility helpers for Python 3.10."""

from __future__ import annotations

import sys

if sys.version_info >= (3, 11):
    from enum import StrEnum
else:
    from enum import Enum

    class StrEnum(str, Enum):
        """Minimal StrEnum backport (str() returns the value)."""

        def __str__(self) -> str:
            return str(self.value)

        @staticmethod
        def _generate_next_value_(name, start, count, last_values):
            return name.lower()


__all__ = ["StrEnum"]
