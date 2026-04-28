from __future__ import annotations

import pandas as pd
import pytest
import warnings

from open_fdd.desktop.services.time_utils import infer_timestamp_column, parse_timestamp_series


def test_infer_timestamp_column_prefers_timestamp() -> None:
    frame = pd.DataFrame({"timestamp": ["2026-01-01T00:00:00Z"], "x": [1]})
    assert infer_timestamp_column(frame) == "timestamp"


def test_parse_timestamp_series_raises_when_invalid_ratio_low() -> None:
    frame = pd.DataFrame({"not_time": ["a", "b", "c", "2026-01-01"]})
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", message="Could not infer format")
        with pytest.raises(ValueError, match="No valid timestamp column found"):
            parse_timestamp_series(frame, timestamp_col="not_time", min_valid_ratio=0.5)
