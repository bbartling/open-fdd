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
    ts_vals = [r["ts_ms"] for r in window_rows if r.get("ts_ms") is not None]
    if len(ts_vals) < 2:
        return False
    span_ms = max(ts_vals) - min(ts_vals)
    return span_ms >= ONE_HOUR_MS * FILL_RATIO


"""Cookbook Recipe 1 — flatline over 1 hour (temp or RH via row['temp'])."""

def evaluate(row, cfg, prev_row=None, rows=None):
    if rows is None:
        return False

    window_rows = window_rows_1h(row, rows)
    if not hour_window_ready(window_rows):
        return False

    sym = temp_unit_symbol(cfg)
    tol_key = "flatline_tolerance_rh" if row.get("value_kind") == "rh" else "flatline_tolerance"
    vals = [r.get("temp") for r in window_rows if r.get("temp") is not None]
    if not vals:
        return False
    spread = max(vals) - min(vals)
    tol = cfg_threshold(cfg, tol_key)

    if spread < tol:
        print(
            f"row={row['row']} ts={row['ts']} "
            f"FLATLINE 1h spread={spread:.3f} < tol={tol:.3f} {sym} col={row.get('value_column')}"
        )
        return True, window_rows

    return False