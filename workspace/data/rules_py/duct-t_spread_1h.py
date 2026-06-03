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


"""Cookbook Recipe 4 — min-max spread over 1 hour."""


def evaluate(row, cfg, prev_row=None, rows=None):
    if rows is None:
        return False

    window_rows = window_rows_1h(row, rows)
    if not hour_window_ready(window_rows):
        return False

    sym = temp_unit_symbol(cfg)
    vals = [r.get("temp") for r in window_rows if r.get("temp") is not None]
    if not vals:
        return False
    spread = max(vals) - min(vals)
    lim = cfg_threshold(cfg, "max_spread")

    if spread > lim:
        print(
            f"row={row['row']} ts={row['ts']} "
            f"SPREAD/1h={spread:.2f} {sym} > {lim:.2f} col={row.get('value_column')}"
        )
        return True, window_rows

    return False
