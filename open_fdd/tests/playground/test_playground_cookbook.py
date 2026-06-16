from open_fdd.playground.cookbook import (
    cfg_threshold,
    hour_window_ready,
    window_rows_1h,
)


def test_cfg_threshold_defaults():
    assert cfg_threshold({}, "bounds_low") == 65.0
    assert cfg_threshold({"bounds_low": 68}, "bounds_low") == 68.0


def test_window_rows_1h_and_ready():
    rows = [{"ts_ms": i * 60_000, "temp": 70.0} for i in range(70)]
    row = rows[-1]
    window = window_rows_1h(row, rows)
    assert len(window) >= 2
    assert hour_window_ready(window)


def test_cfg_threshold_malformed_config():
    assert cfg_threshold({"bounds_low": "bad"}, "bounds_low") == 65.0
    assert cfg_threshold({"bounds_low": None}, "bounds_low") == 65.0
