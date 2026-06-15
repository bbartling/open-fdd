from __future__ import annotations

import pyarrow as pa
import pytest

from open_fdd.arrow_runtime.confirmation import confirm_fault_mask


def test_min_true_rows_five_consecutive():
    raw = pa.array([True, True, True, True, True], type=pa.bool_())
    confirmed, meta = confirm_fault_mask(raw, min_true_rows=5)
    assert meta["min_true_rows"] == 5
    assert confirmed.to_pylist() == [False, False, False, False, True]


def test_min_true_rows_resets_on_false():
    raw = pa.array([True, True, False, True, True, True], type=pa.bool_())
    confirmed, _meta = confirm_fault_mask(raw, min_true_rows=3)
    assert confirmed.to_pylist() == [False, False, False, False, False, True]


def test_null_resets_streak():
    raw = pa.array([True, None, True, True, True], type=pa.bool_())
    confirmed, _meta = confirm_fault_mask(raw, min_true_rows=3)
    assert confirmed.to_pylist()[2] is False


def test_min_elapsed_minutes_with_timestamps():
    ts = pa.array(
        [
            "2026-01-01T00:00:00Z",
            "2026-01-01T00:01:00Z",
            "2026-01-01T00:02:00Z",
            "2026-01-01T00:03:00Z",
            "2026-01-01T00:04:00Z",
            "2026-01-01T00:05:00Z",
        ]
    )
    table = pa.table({"timestamp": ts})
    raw = pa.array([True] * 6, type=pa.bool_())
    confirmed, meta = confirm_fault_mask(
        raw,
        table,
        min_elapsed_minutes=5.0,
        timestamp_column="timestamp",
    )
    assert meta["min_elapsed_minutes"] == 5.0
    assert confirmed.to_pylist()[:5] == [False] * 5
    assert confirmed.to_pylist()[5] is True


def test_poll_interval_fallback_warning():
    raw = pa.array([True, True, True, True, True], type=pa.bool_())
    confirmed, meta = confirm_fault_mask(
        raw,
        None,
        min_elapsed_minutes=5.0,
        poll_interval_s=60.0,
    )
    assert "warning" in meta
    assert confirmed.to_pylist() == [False, False, False, False, True]
