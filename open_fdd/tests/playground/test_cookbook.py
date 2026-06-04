from open_fdd.playground.cookbook import (
    cfg_threshold,
    hour_window_ready,
    window_rows_1h,
)
from open_fdd.playground.rows import dataframe_to_evaluate_rows, readings_to_evaluate_rows


def test_cfg_threshold_defaults():
    assert cfg_threshold({}, "bounds_low") == 65.0
    assert cfg_threshold({"bounds_low": 68}, "bounds_low") == 68.0


def test_window_rows_1h_and_ready():
    rows = [{"ts_ms": i * 60_000, "temp": 70.0} for i in range(70)]
    row = rows[-1]
    window = window_rows_1h(row, rows)
    assert len(window) >= 2
    assert hour_window_ready(window)


def test_readings_to_evaluate_rows():
    readings = [{"ts_ms": 1_700_000_000_000, "degF": 72.0, "ts": "2024-01-01T12:00:00Z"}]
    rows = readings_to_evaluate_rows(readings)
    assert rows[0]["temp"] == 72.0
    assert "temp_rolling_avg" in rows[0]


def test_dataframe_to_evaluate_rows():
    import pandas as pd

    df = pd.DataFrame(
        {
            "timestamp": pd.date_range("2024-01-01", periods=5, freq="5min", tz="UTC"),
            "zone_t": [70.0, 70.1, 70.2, 70.3, 70.4],
        }
    )
    rows = dataframe_to_evaluate_rows(df, "zone_t")
    assert len(rows) == 5
    assert rows[-1]["temp_rolling_avg"] is not None
