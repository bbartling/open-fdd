"""Cookbook Recipe 1 — flatline over 1 hour (temp or RH via row['temp'])."""

from open_fdd.playground.cookbook import cfg_threshold, hour_window_ready, temp_unit_symbol, window_rows_1h


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
