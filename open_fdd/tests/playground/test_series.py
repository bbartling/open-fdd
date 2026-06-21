import pytest

from open_fdd.playground.series import build_series_context, slim_fdd_summary


def test_slim_fdd_summary_drops_bulk_keys():
    raw = {"fdd_status": "ok", "ts_ms": [1, 2], "flag_series": {"r": [1]}, "aux_series": {}}
    slim = slim_fdd_summary(raw)
    assert slim == {"fdd_status": "ok"}


def test_build_series_context_cross_sensor():
    series_map = {
        "sat": [
            {"ts_ms": 1_000, "value": 55.0},
            {"ts_ms": 2_000, "value": 80.0},
        ],
    }
    ctx = build_series_context(series_map, 1, aliases={"SAT": "sat"})
    assert ctx["SAT"]["current"] == 80.0

