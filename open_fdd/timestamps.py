"""UTC datetime parsing that accepts ISO-8601 ``Z`` and ``+00:00`` without warnings.

BAS packages and gold fixtures mix both suffixes. Bare ``pd.to_datetime(..., utc=True)``
emits ``Could not infer format`` UserWarnings on pandas 2.x — prefer this helper.
"""

from __future__ import annotations

from typing import Any

import pandas as pd


def to_utc_datetime(values: Any, *, errors: str = "coerce") -> pd.Series | pd.DatetimeIndex:
    """Parse timestamps to UTC.

    Tries ``format="ISO8601"`` first (pandas 2.x), then ``format="mixed"``.
    Does not invent wall-clock times for garbage input when ``errors="coerce"``.
    """
    try:
        return pd.to_datetime(values, utc=True, format="ISO8601", errors=errors)
    except (ValueError, TypeError, OverflowError):
        return pd.to_datetime(values, utc=True, format="mixed", errors=errors)
