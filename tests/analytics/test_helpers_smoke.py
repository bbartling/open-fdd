"""Smoke tests for packaged analytics helpers."""

from __future__ import annotations

import pandas as pd

from open_fdd.analytics.poll import infer_poll_seconds
from open_fdd.analytics.runtime_intervals import hours_under_mask
from open_fdd.analytics.site_model import equipment_type_from_id


def test_infer_poll_seconds():
    idx = pd.date_range("2026-01-01", periods=5, freq="5min", tz="UTC")
    df = pd.DataFrame({"x": range(5)}, index=idx)
    assert abs(infer_poll_seconds(df) - 300.0) < 1.0


def test_hours_under_mask():
    idx = pd.date_range("2026-01-01", periods=4, freq="1h", tz="UTC")
    mask = pd.Series([True, True, False, True], index=idx)
    assert hours_under_mask(mask, nominal_seconds=3600.0) >= 0.0


def test_equipment_type_from_id():
    assert "AHU" in equipment_type_from_id("AHU_1").upper()
