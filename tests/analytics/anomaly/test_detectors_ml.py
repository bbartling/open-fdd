"""Python-only STL and Isolation Forest detectors."""

from __future__ import annotations

import sys

import numpy as np
import pandas as pd
import pytest

from open_fdd.analytics.anomaly.detectors_ml import isolation_forest_flags, stl_residual_flags


def test_stl_flags_point_anomaly_and_degrades_when_short():
    pytest.importorskip("statsmodels")
    idx = pd.date_range("2026-01-01", periods=24 * 4, freq="h", tz="UTC")
    t = np.arange(len(idx))
    seasonal = pd.Series(70.0 + 5.0 * np.sin(2.0 * np.pi * t / 24.0), index=idx)
    seasonal.iloc[50] = 140.0
    flags = stl_residual_flags(seasonal, period=24)
    assert bool(flags.iloc[50])

    short = stl_residual_flags(pd.Series([1.0, 2.0, 3.0, 4.0]), period=24)
    assert len(short) == 4
    assert not bool(short.any())


def test_isolation_forest_flags_obvious_spike():
    pytest.importorskip("sklearn")
    rng = np.random.default_rng(1)
    values = pd.Series(rng.normal(70.0, 0.5, 400))
    values.iloc[200] = 160.0
    flags = isolation_forest_flags(values, contamination=0.02, random_state=42)
    assert bool(flags.iloc[200])


def test_missing_anomaly_extra_names_the_install(monkeypatch):
    real_import = __import__

    def _blocked(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "sklearn.ensemble" or name.startswith("statsmodels"):
            raise ImportError("simulated missing extra")
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr("builtins.__import__", _blocked)
    for key in list(sys.modules):
        if key == "sklearn" or key.startswith("sklearn.") or key.startswith("statsmodels"):
            monkeypatch.delitem(sys.modules, key, raising=False)

    with pytest.raises(ImportError, match=r"open-fdd\[anomaly\]"):
        isolation_forest_flags(pd.Series([1.0, 2.0, 3.0, 4.0]))
    with pytest.raises(ImportError, match=r"open-fdd\[anomaly\]"):
        stl_residual_flags(pd.Series(np.linspace(0, 1, 80)), period=12)
