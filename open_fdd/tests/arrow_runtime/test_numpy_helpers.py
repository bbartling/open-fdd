from __future__ import annotations

import pytest

pa = pytest.importorskip("pyarrow")
np = pytest.importorskip("numpy")

from open_fdd.arrow_runtime.numpy_helpers import pearson_correlation, rolling_mean


def test_rolling_mean_numpy():
    arr = pa.array([1.0, 2.0, 3.0, 4.0])
    out = rolling_mean(arr, 2)
    assert len(out) == 4
    assert out[1].as_py() == pytest.approx(1.5)


def test_pearson_correlation():
    x = pa.array([1.0, 2.0, 3.0, 4.0])
    y = pa.array([2.0, 4.0, 6.0, 8.0])
    r = pearson_correlation(x, y)
    assert r is not None and r == pytest.approx(1.0)
