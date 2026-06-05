from __future__ import annotations

import pyarrow as pa

from open_fdd.arrow_runtime.windows import arrow_consecutive_true, arrow_diff, arrow_shift


def test_shift_and_diff():
    arr = pa.array([10.0, 12.0, 15.0])
    shifted = arrow_shift(arr, 1)
    assert shifted[0].as_py() is None
    assert shifted[1].as_py() == 10.0
    d = arrow_diff(arr, 1)
    assert d[1].as_py() == 2.0


def test_consecutive_true():
    mask = pa.array([True, True, False, True, True, True])
    out = arrow_consecutive_true(mask, 3)
    assert out[2].as_py() is True
    assert out[3].as_py() is False
