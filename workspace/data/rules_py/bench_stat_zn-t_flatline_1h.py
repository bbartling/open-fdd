"""Cookbook Recipe 1 — flatline over 1 hour (temp or rh via row['temp'])."""

ONE_HOUR_MS = 60 * 60 * 1000
FILL_RATIO = 0.95


def get_last_1_hour(row, rows):
    now_ms = row["ts_ms"]
    start_ms = now_ms - ONE_HOUR_MS
    return [r for r in rows if start_ms <= r["ts_ms"] <= now_ms]


def evaluate(row, cfg, prev_row=None, rows=None):
    if rows is None:
        return False

    window_rows = get_last_1_hour(row, rows)
    if len(window_rows) < 2:
        return False

    span_ms = window_rows[-1]["ts_ms"] - window_rows[0]["ts_ms"]
    if span_ms < ONE_HOUR_MS * FILL_RATIO:
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
            f"FLATLINE 1h spread={spread:.3f} < tol={tol:.3f} col={row.get('value_column')}"
        )
        return True, window_rows

    return False
