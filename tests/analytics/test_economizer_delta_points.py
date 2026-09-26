"""Canonical economizer mixing axes: x = OAT−RAT, y = MAT−RAT."""

from __future__ import annotations

import pandas as pd

from open_fdd.analytics.charts import economizer_delta_scatter
from open_fdd.analytics.core import build_economizer_delta_points


def _frame(oat, rat, mat, fan) -> pd.DataFrame:
    n = len(oat)
    return pd.DataFrame(
        {
            "outside-air-temp": oat,
            "return-air-temp": rat,
            "mixed-air-temp": mat,
            "fan-status": fan,
        }
    )


def test_full_oa_lands_on_yx_and_zero_oa_lands_on_y0():
    full = _frame([40.0] * 6, [70.0] * 6, [40.0] * 6, [1] * 6)
    zero = _frame([40.0] * 6, [70.0] * 6, [70.0] * 6, [1] * 6)

    full_pts = build_economizer_delta_points(full, equipment_id="AHU_1")
    zero_pts = build_economizer_delta_points(zero, equipment_id="AHU_1")

    assert set(c for c in full_pts.columns if c.startswith("delta_")) == {"delta_or_f", "delta_mr_f"}
    assert "oat_minus_mat" not in full_pts.columns
    assert "rat_minus_mat" not in full_pts.columns

    # 100% OA: MAT = OAT → y ≈ x. 0% OA: MAT = RAT → y ≈ 0.
    assert (full_pts["delta_mr_f"] - full_pts["delta_or_f"]).abs().max() < 1e-9
    assert full_pts["delta_or_f"].iloc[0] == 40.0 - 70.0
    assert zero_pts["delta_mr_f"].abs().max() < 1e-9
    assert zero_pts["delta_or_f"].iloc[0] == 40.0 - 70.0
    assert bool(full_pts["identifiable"].all())
    assert bool(zero_pts["identifiable"].all())

    figure = economizer_delta_scatter(full_pts)
    assert figure is not None
    assert figure.layout.xaxis.title.text == "OAT − RAT (°F)"
    assert figure.layout.yaxis.title.text == "MAT − RAT (°F)"


def test_bottom_left_viewport_clips_to_nonpositive_deltas():
    """Mixing diagnostics view only OAT≤RAT and MAT≤RAT (both deltas ≤ 0)."""
    frame = _frame(
        oat=[40.0] * 6 + [90.0] * 6,
        rat=[70.0] * 12,
        mat=[40.0] * 6 + [90.0] * 6,
        fan=[1] * 12,
    )
    points = build_economizer_delta_points(frame, equipment_id="AHU_1")
    assert (points["delta_or_f"].iloc[:6] < 0).all()
    assert (points["delta_or_f"].iloc[6:] > 0).all()

    figure = economizer_delta_scatter(points, viewport="bottom_left")
    assert figure is not None
    x_range = list(figure.layout.xaxis.range)
    y_range = list(figure.layout.yaxis.range)
    assert x_range[1] == 0.0
    assert y_range[1] == 0.0
    assert x_range[0] < 0
    assert y_range[0] < 0
    assert "bottom-left" in figure.layout.title.text
    xs = []
    for trace in figure.data:
        if trace.mode == "markers":
            xs.extend(float(v) for v in trace.x)
    assert xs
    assert max(xs) <= 0.0


def test_fan_off_dropped_and_small_delta_not_identifiable():
    frame = _frame(
        oat=[40.0, 40.0, 72.0],
        rat=[70.0, 70.0, 75.0],
        mat=[40.0, 40.0, 73.0],
        fan=[1, 0, 1],
    )
    points = build_economizer_delta_points(frame)
    assert len(points) == 2
    assert bool(points["identifiable"].iloc[0])
    assert not bool(points["identifiable"].iloc[1])
    assert abs(float(points["delta_or_f"].iloc[1])) < 10.0
