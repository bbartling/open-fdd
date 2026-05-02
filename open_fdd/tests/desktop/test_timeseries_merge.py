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


def test_merge_single_source_duplicate_timestamp_labels_still_parses() -> None:
    """Regression: duplicate column labels make df['timestamp'] a DataFrame; pd.to_datetime must not crash."""
    t = pd.Timestamp("2026-01-01T00:00:00Z", tz="UTC")
    raw = pd.DataFrame([[t, t, 55.0]], columns=["timestamp", "timestamp", "sat"])
    out, used = merge_site_frames_on_timestamp([("csv", raw)])
    assert used == ["csv"]
    assert len(out) == 1
    assert out.columns.is_unique
    assert "sat" in out.columns
    assert float(out.iloc[0]["sat"]) == 55.0


def test_merge_two_sources_both_had_duplicate_timestamp_labels() -> None:
    t1 = pd.Timestamp("2026-01-01T00:00:00Z", tz="UTC")
    t2 = pd.Timestamp("2026-01-01T01:00:00Z", tz="UTC")
    csv_part = pd.DataFrame([[t1, t1, 50.0]], columns=["timestamp", "timestamp", "sat"])
    wx_part = pd.DataFrame([[t1, t1, 30.0]], columns=["timestamp", "timestamp", "oat"])
    out, used = merge_site_frames_on_timestamp([("csv", csv_part), ("weather", wx_part)])
    assert used == ["csv", "weather"]
    assert out.columns.is_unique
    assert len(out) == 1
    assert "sat_csv" in out.columns
    assert "oat_weather" in out.columns


def test_merge_duplicate_timestamps_deduped_no_cartesian_explosion() -> None:
    ts = pd.Timestamp("2026-01-01T00:00:00Z")
    csv_part = pd.DataFrame({"timestamp": [ts, ts, ts], "sat": [50.0, 51.0, 52.0]})
    wx_part = pd.DataFrame({"timestamp": [ts, ts], "oat": [30.0, 31.0]})
    out, used = merge_site_frames_on_timestamp([("csv", csv_part), ("weather", wx_part)])
    assert used == ["csv", "weather"]
    assert len(out) == 1
    assert float(out.iloc[0]["sat_csv"]) == 52.0
    assert float(out.iloc[0]["oat_weather"]) == 31.0
