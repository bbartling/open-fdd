"""UTC timestamp helper — Z and +00:00 without pandas format warnings."""

from __future__ import annotations

import warnings

import pandas as pd

from open_fdd.timestamps import to_utc_datetime


def test_mixed_z_and_offset_no_userwarning():
    series = pd.Series(
        [
            "2026-05-21T20:20:00Z",
            "2026-05-21T20:25:00+00:00",
            "2026-05-21T20:30:00Z",
        ]
    )
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        out = to_utc_datetime(series)
    assert not any(
        issubclass(w.category, UserWarning) and "infer format" in str(w.message).lower()
        for w in caught
    ), [str(w.message) for w in caught]
    assert len(out) == 3
    assert out.notna().all()
    assert out.dt.tz is not None
    assert out.iloc[0].value == out.iloc[0].tz_convert("UTC").value
