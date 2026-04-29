"""Merge-on-read for multi-driver site frames."""

from __future__ import annotations

import pandas as pd
import pytest

from open_fdd.desktop.services.timeseries_merge import merge_site_frames_on_timestamp


def test_merge_single_source_no_metric_suffix() -> None:
    ts = pd.date_range("2026-01-01", periods=3, freq="h", tz="UTC")
    df = pd.DataFrame({"timestamp": ts, "oat": [1.0, 2.0, 3.0]})
    out, used = merge_site_frames_on_timestamp([("csv", df)])
    assert used == ["csv"]
    assert list(out.columns) == ["timestamp", "oat"]
    assert len(out) == 3


def test_merge_two_sources_suffixes_metrics() -> None:
    ts = pd.date_range("2026-01-01", periods=2, freq="h", tz="UTC")
    csv_part = pd.DataFrame({"timestamp": ts, "sat": [50.0, 51.0]})
    wx_part = pd.DataFrame({"timestamp": ts, "oat": [30.0, 31.0]})
    out, used = merge_site_frames_on_timestamp([("csv", csv_part), ("weather", wx_part)])
    assert used == ["csv", "weather"]
    assert "timestamp" in out.columns
    assert "sat_csv" in out.columns
    assert "oat_weather" in out.columns
    assert len(out) == 2


def test_merge_skips_empty_frames() -> None:
    ts = pd.date_range("2026-01-01", periods=1, freq="h", tz="UTC")
    csv_part = pd.DataFrame({"timestamp": ts, "x": [1.0]})
    empty = pd.DataFrame()
    out, used = merge_site_frames_on_timestamp([("csv", csv_part), ("bacnet", empty)])
    assert used == ["csv"]
    assert "x" in out.columns  # single contributor after skipping empty
    assert len(out) == 1


def test_merge_returns_empty_for_all_empty() -> None:
    out, used = merge_site_frames_on_timestamp([("csv", pd.DataFrame()), ("weather", pd.DataFrame())])
    assert used == []
    assert out.empty
