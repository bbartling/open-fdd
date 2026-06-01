"""Cookbook Recipe 4 — spread / min-max over 1 hour."""

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
    if not window_rows:
        return False

    span_ms = window_rows[-1]["ts_ms"] - window_rows[0]["ts_ms"]
    if span_ms < ONE_HOUR_MS * FILL_RATIO:
        return False

    sym = temp_unit_symbol(cfg)
    vals = [r.get("temp") for r in window_rows if r.get("temp") is not None]
    if not vals:
        return False
    lo, hi = min(vals), max(vals)
    spread = hi - lo
    lim = cfg_threshold(cfg, "max_spread")

    if spread > lim:
        print(
            f"row={row['row']} ts={row['ts']} "
            f"SPREAD/1h={spread:.2f} {sym} > {lim:.2f} col={row.get('value_column')}"
        )
        return True, window_rows

    return False
