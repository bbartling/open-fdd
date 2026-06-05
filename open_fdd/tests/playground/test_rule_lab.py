from open_fdd.playground.rule_lab import (
    GO_LIVE_BATCH_HOURS,
    readings_to_rows,
    slim_fdd_summary,
    sweep_rule,
)


def test_rule_lab_sweep_oob():
    code = """
def evaluate(row, cfg, prev_row=None, rows=None):
    v = row.get("temp_rolling_avg") or row.get("temp")
    return v is not None and v > cfg.get("bounds_high", 80)
"""
    rows = readings_to_rows(
        [
            {"ts_ms": 1, "ts_iso": "2024-01-01T00:00:00Z", "degF": 70.0, "degC": 21.1},
            {"ts_ms": 2, "ts_iso": "2024-01-01T00:01:00Z", "degF": 90.0, "degC": 32.2},
        ]
    )
    flags, events = sweep_rule(code, {"bounds_high": 79}, rows, capture_print=False)
    assert flags[-1] == 1
    assert not any(e.get("type") == "error" for e in events)


def test_go_live_constants():
    assert GO_LIVE_BATCH_HOURS == 6


def test_slim_summary():
    assert slim_fdd_summary({"a": 1, "flag_series": {}}) == {"a": 1}
