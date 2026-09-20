"""Unit tests for ASHRAE G14 NMBE / CVRMSE helpers."""

from __future__ import annotations

import pytest

from open_fdd.ecm_engineering import (
    cvrmse_pct,
    nmbe_pct,
    score_g14,
    score_g14_fuels,
    score_g14_monthly,
)


def test_perfect_fit_is_zero_error():
    m = [100.0, 110.0, 90.0, 105.0]
    assert nmbe_pct(m, m, n_params=1) == pytest.approx(0.0)
    assert cvrmse_pct(m, m, n_params=1) == pytest.approx(0.0)
    score = score_g14_monthly(m, m, n_params=1)
    assert score.pass_ is True
    assert score.to_dict()["pass"] is True


def test_biased_prediction_fails_monthly_gate():
    measured = [100.0] * 12
    predicted = [80.0] * 12  # 20% low → large |NMBE|
    score = score_g14(measured, predicted, granularity="monthly", n_params=1)
    assert abs(score.nmbe_pct) > 5.0
    assert score.pass_ is False


def test_hourly_thresholds_looser_than_monthly():
    measured = [100.0, 100.0, 100.0, 100.0]
    # ~8% CVRMSE-ish / moderate bias — may pass hourly, fail monthly depending on n_params
    predicted = [92.0, 108.0, 95.0, 105.0]
    monthly = score_g14(measured, predicted, granularity="monthly", n_params=1)
    hourly = score_g14(measured, predicted, granularity="hourly", n_params=1)
    assert monthly.nmbe_pct == pytest.approx(hourly.nmbe_pct)
    assert monthly.cvrmse_pct == pytest.approx(hourly.cvrmse_pct)
    # Same metrics; hourly allows higher thresholds
    if not monthly.pass_:
        # If monthly fails, hourly may still pass when within 10/30
        assert hourly.pass_ or abs(hourly.nmbe_pct) > 10.0 or hourly.cvrmse_pct > 30.0


def test_score_g14_fuels_requires_both():
    m = [100.0, 110.0, 90.0, 105.0, 95.0, 100.0, 102.0, 98.0, 101.0, 99.0, 100.0, 100.0]
    out = score_g14_fuels(
        elec_measured=m,
        elec_predicted=m,
        gas_measured=m,
        gas_predicted=m,
        n_params=1,
    )
    assert out["pass"] is True
    assert set(out["fuels"]) == {"elec", "gas"}


def test_mean_zero_raises():
    with pytest.raises(ValueError, match="mean measured"):
        nmbe_pct([0.0, 0.0], [1.0, -1.0])
