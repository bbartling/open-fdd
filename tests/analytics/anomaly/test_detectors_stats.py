"""SQL-portable Z-score and MAD detectors (no sklearn / statsmodels)."""

from __future__ import annotations

import ast
from pathlib import Path

import numpy as np
import pandas as pd

from open_fdd.analytics.anomaly.detectors import (
    anomaly_minutes,
    dedupe_events,
    is_binary_like,
    rolling_mad_flags,
    rolling_zscore_flags,
    samples_per_day,
)

_DETECTORS = Path(__file__).resolve().parents[3] / "open_fdd" / "analytics" / "anomaly" / "detectors.py"


def test_detectors_module_has_no_sklearn_or_statsmodels_imports():
    tree = ast.parse(_DETECTORS.read_text(encoding="utf-8"))
    banned = ("sklearn", "statsmodels")
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            names = [node.module or ""]
        else:
            continue
        for name in names:
            assert not any(name == banned_name or name.startswith(banned_name + ".") for banned_name in banned)


def test_zscore_flags_spike_and_ignores_constant_series():
    flat = pd.Series([55.0] * 36)
    assert not bool(rolling_zscore_flags(flat, window=12, threshold=3.0).any())

    spiked = pd.Series([70.0] * 48)
    spiked.iloc[40] = 200.0
    flags = rolling_zscore_flags(spiked, window=24, threshold=3.0)
    assert bool(flags.iloc[40])
    assert int(flags.sum()) < 8


def test_mad_flags_spike_when_window_has_noise():
    rng = np.random.default_rng(0)
    values = 70.0 + rng.normal(0, 0.4, 80)
    values[60] = 120.0
    flags = rolling_mad_flags(pd.Series(values), window=24, threshold=3.5)
    assert bool(flags.iloc[60])
    assert int(flags.sum()) < 12


def test_mad_guards_zero_mad_on_constant_series():
    flags = rolling_mad_flags(pd.Series([55.0] * 30), window=10, threshold=3.5)
    assert not bool(flags.any())


def test_dedupe_keeps_false_to_true_edges_only():
    flags = pd.Series([False, True, True, False, True])
    events = dedupe_events(flags)
    assert list(events.astype(bool)) == [False, True, False, False, True]


def test_leading_true_counts_as_an_event():
    events = dedupe_events(pd.Series([True, True, False]))
    assert list(events.astype(bool)) == [True, False, False]


def test_anomaly_minutes_uses_flagged_sample_count():
    flags = pd.Series([True, False, True, True])
    assert anomaly_minutes(flags, pd.Timedelta(minutes=15)) == 45.0


def test_binary_like_max_unique():
    assert is_binary_like(pd.Series([0, 1, 0, 1]))
    assert is_binary_like(pd.Series([0.0, 1.0, 0.5]))
    assert not is_binary_like(pd.Series([70.0, 71.0, 72.0, 73.0]))


def test_samples_per_day_from_median_interval():
    hourly = pd.date_range("2026-01-01", periods=10, freq="h", tz="UTC")
    assert samples_per_day(hourly) == 24
    fifteen = pd.date_range("2026-01-01", periods=10, freq="15min", tz="UTC")
    assert samples_per_day(fifteen) == 96
