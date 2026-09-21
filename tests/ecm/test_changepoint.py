"""Unit tests for IPMVP change-point / Option C helpers."""

from __future__ import annotations

import numpy as np
import pytest

from open_fdd.ecm_engineering import fit_changepoint, option_c_savings, select_changepoint
from open_fdd.ecm_engineering.changepoint import predict_changepoint


def _synthetic_3pc(*, n: int = 40, bp: float = 55.0, a: float = 200.0, b: float = 8.0):
    rng = np.random.default_rng(7)
    x = np.linspace(30.0, 90.0, n)
    y = a + b * np.maximum(x - bp, 0.0) + rng.normal(0.0, 2.0, size=n)
    return x, y


def test_fit_3pc_recovers_cooling_slope():
    x, y = _synthetic_3pc()
    model = fit_changepoint(x, y, kind="3PC", grid=40)
    assert model.kind == "3PC"
    assert model.change_point == pytest.approx(55.0, abs=5.0)
    assert model.slope_cool == pytest.approx(8.0, abs=1.5)
    assert model.r_squared > 0.95
    yhat = predict_changepoint(model, x)
    assert yhat.shape == x.shape


def test_2p_linear_fit():
    x = np.linspace(40.0, 80.0, 30)
    y = 10.0 + 2.5 * x
    model = fit_changepoint(x, y, kind="2P")
    assert model.kind == "2P"
    assert model.intercept == pytest.approx(10.0, abs=1e-6)
    assert model.slope_cool == pytest.approx(2.5, abs=1e-6)
    assert model.cvrmse_pct == pytest.approx(0.0, abs=1e-6)


def test_select_prefers_low_cvrmse():
    x, y = _synthetic_3pc()
    model = select_changepoint(x, y, kinds=("2P", "3PC", "4P"), grid=30)
    assert model.kind in {"3PC", "4P", "2P"}
    assert model.cvrmse_pct < 15.0


def test_option_c_positive_savings():
    x, y = _synthetic_3pc()
    baseline = fit_changepoint(x, y, kind="3PC", grid=40)
    # Reporting period: same weather, 10% lower energy
    reporting_y = y * 0.9
    out = option_c_savings(baseline, reporting_x=x, reporting_y=reporting_y)
    assert out["savings_total"] > 0
    assert out["n"] == len(x)
    assert out["baseline_kind"] == "3PC"


def test_analytics_reexports():
    import open_fdd.analytics as a

    assert hasattr(a, "fit_changepoint")
    assert hasattr(a, "score_g14_monthly")
    assert hasattr(a, "ChangePointModel")
