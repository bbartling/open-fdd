from open_fdd.playground.series import (
    build_series_context,
    evaluate_rules_on_series,
    slim_fdd_summary,
)


def test_slim_fdd_summary_drops_bulk_keys():
    raw = {"fdd_status": "ok", "ts_ms": [1, 2], "flag_series": {"r": [1]}, "aux_series": {}}
    slim = slim_fdd_summary(raw)
    assert slim == {"fdd_status": "ok"}


def test_evaluate_rules_on_series_cross_sensor():
    rows = [
        {"row": 0, "ts_ms": 1_000, "ts": "t0", "degF": 70.0, "temp": 70.0},
        {"row": 1, "ts_ms": 2_000, "ts": "t1", "degF": 90.0, "temp": 90.0},
    ]
    series_map = {
        "sat": [
            {"ts_ms": 1_000, "value": 55.0},
            {"ts_ms": 2_000, "value": 80.0},
        ],
    }
    code = """
def evaluate(row, cfg, prev_row=None, rows=None, series=None):
    sat = series["SAT"]["current"]
    return sat is not None and sat > 60
"""
    rules = [
        {
            "id": "sat_high",
            "enabled": True,
            "code": code,
            "config": {"series_aliases": {"SAT": "sat"}},
        }
    ]
    flags = evaluate_rules_on_series(rules, rows, series_map)
    assert flags["sat_high"] == [0, 1]

    ctx = build_series_context(series_map, 1, aliases={"SAT": "sat"})
    assert ctx["SAT"]["current"] == 80.0
