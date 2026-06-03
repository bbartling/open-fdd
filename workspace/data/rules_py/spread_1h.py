"""Cookbook Recipe 4 — min-max spread over 1 hour."""

from bench_fdd_common import hour_window_ready, window_rows_1h


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
