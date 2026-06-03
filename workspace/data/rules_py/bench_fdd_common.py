"""Shared cookbook helpers for bensserver bench FDD rules (inlined via setup_bench_afdd)."""

ONE_HOUR_MS = 60 * 60 * 1000
FILL_RATIO = 0.95


def window_rows_1h(row, rows):
    now_ms = row["ts_ms"]
    start_ms = now_ms - ONE_HOUR_MS
    return [r for r in rows if start_ms <= r["ts_ms"] <= now_ms]


def hour_window_ready(window_rows):
    if len(window_rows) < 2:
        return False
    span_ms = window_rows[-1]["ts_ms"] - window_rows[0]["ts_ms"]
    return span_ms >= ONE_HOUR_MS * FILL_RATIO
