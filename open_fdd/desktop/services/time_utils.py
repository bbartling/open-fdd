from __future__ import annotations

from typing import Iterable
import re

import pandas as pd
from pydantic import BaseModel, ConfigDict, Field

_TZ_ABBREV_OFFSETS = {
    "UTC": "+00:00",
    "GMT": "+00:00",
    "EDT": "-04:00",
    "EST": "-05:00",
    "CDT": "-05:00",
    "CST": "-06:00",
    "MDT": "-06:00",
    "MST": "-07:00",
    "PDT": "-07:00",
    "PST": "-08:00",
}

_TZ_SUFFIX_RE = re.compile(r"^(?P<prefix>.+?)\s+(?P<abbr>[A-Za-z]{3,4})$")


class TimestampParsePolicy(BaseModel):
    """
    Runtime parsing policy for timestamp columns.
    """

    model_config = ConfigDict(extra="forbid")
    min_valid_ratio: float = Field(default=0.5, gt=0.0, le=1.0)
    normalize_known_tz_abbreviations: bool = True


def infer_timestamp_column(frame: pd.DataFrame, *, candidate_names: Iterable[str] | None = None) -> str:
    """
    Pick the most likely timestamp column from a frame.

    Preference order:
    1) exact "timestamp" (case-insensitive)
    2) configured candidate names
    3) first column whose name contains "time" or "date"
    4) first frame column as last resort
    """
    cols = [str(c) for c in frame.columns]
    if not cols:
        raise ValueError("Frame has no columns to infer timestamp from.")
    for c in cols:
        if c.strip().casefold() == "timestamp":
            return c
    for name in list(candidate_names or []):
        for c in cols:
            if c.strip().casefold() == str(name).strip().casefold():
                return c
    for c in cols:
        lower = c.strip().casefold()
        if "time" in lower or "date" in lower:
            return c
    return cols[0]


def parse_timestamp_series(
    frame: pd.DataFrame,
    *,
    timestamp_col: str,
    min_valid_ratio: float = 0.5,
    policy: TimestampParsePolicy | None = None,
) -> pd.Series:
    """
    Parse a timestamp column and validate minimum parse success.
    """
    cfg = policy or TimestampParsePolicy(min_valid_ratio=min_valid_ratio)
    series = frame[timestamp_col]
    if cfg.normalize_known_tz_abbreviations:
        series = normalize_known_timezone_abbreviations(series)
    parsed = pd.to_datetime(series, errors="coerce", utc=True)
    if len(parsed.index) == 0:
        raise ValueError(f"No rows available in timestamp column '{timestamp_col}'.")
    valid_ratio = float(parsed.notna().mean())
    if valid_ratio < max(0.01, min(1.0, float(cfg.min_valid_ratio))):
        sample_cols = ", ".join([str(c) for c in frame.columns[:10]])
        raise ValueError(
            f"No valid timestamp column found. Candidate '{timestamp_col}' parse ratio={valid_ratio:.2f}. "
            f"Available columns: {sample_cols}"
        )
    return parsed


def normalize_known_timezone_abbreviations(series: pd.Series) -> pd.Series:
    """
    Normalize trailing timezone abbreviations (e.g. EDT) into UTC offsets.
    """

    def _normalize(value: object) -> object:
        if pd.isna(value):
            return value
        text = str(value).strip()
        if not text:
            return value
        match = _TZ_SUFFIX_RE.match(text)
        if not match:
            return value
        abbr = str(match.group("abbr")).upper()
        offset = _TZ_ABBREV_OFFSETS.get(abbr)
        if not offset:
            return value
        return f"{match.group('prefix')} {offset}"

    return series.map(_normalize)
