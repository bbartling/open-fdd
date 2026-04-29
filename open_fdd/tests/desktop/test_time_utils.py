from __future__ import annotations

import pandas as pd
import pytest

from open_fdd.desktop.services.time_utils import (
    TimestampParsePolicy,
    infer_timestamp_column,
    normalize_known_timezone_abbreviations,
    parse_timestamp_series,
)


def test_infer_timestamp_column_prefers_timestamp() -> None:
    frame = pd.DataFrame({"timestamp": ["2026-01-01T00:00:00Z"], "x": [1]})
    assert infer_timestamp_column(frame) == "timestamp"


def test_parse_timestamp_series_raises_when_invalid_ratio_low() -> None:
    frame = pd.DataFrame({"not_time": ["a", "b", "c", "2026-01-01"]})
    with pytest.raises(ValueError, match="No valid timestamp column found"):
        parse_timestamp_series(frame, timestamp_col="not_time", min_valid_ratio=0.5)


def test_parse_timestamp_series_normalizes_known_timezone_abbrev() -> None:
    frame = pd.DataFrame({"timestamp": ["18-Mar-26 9:00:00 PM EDT", "18-Mar-26 10:00:00 PM EDT"]})
    parsed = parse_timestamp_series(
        frame,
        timestamp_col="timestamp",
        policy=TimestampParsePolicy(min_valid_ratio=0.5, normalize_known_tz_abbreviations=True),
    )
    assert parsed.notna().all()


def test_normalize_known_timezone_abbreviations_rewrites_suffix() -> None:
    series = pd.Series(["18-Mar-26 9:00:00 PM EDT", "2026-03-18T21:00:00Z"])
    out = normalize_known_timezone_abbreviations(series)
    assert str(out.iloc[0]).endswith("-04:00")
    assert str(out.iloc[1]) == "2026-03-18T21:00:00Z"


def test_timezone_normalization_handles_na_and_blank_values() -> None:
    frame = pd.DataFrame({"timestamp": ["18-Mar-26 9:00:00 PM EDT", pd.NA, ""]})
    normalized = normalize_known_timezone_abbreviations(frame["timestamp"])
    assert str(normalized.iloc[0]).endswith("-04:00")
    assert pd.isna(normalized.iloc[1])
    parsed = parse_timestamp_series(
        pd.DataFrame({"timestamp": normalized}),
        timestamp_col="timestamp",
        policy=TimestampParsePolicy(min_valid_ratio=0.3, normalize_known_tz_abbreviations=True),
    )
    assert parsed.notna().sum() == 1
