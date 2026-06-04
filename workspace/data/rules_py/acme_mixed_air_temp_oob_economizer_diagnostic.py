"""Cookbook Recipe 6 — out of bounds on rolling avg."""

from open_fdd.playground.cookbook import cfg_threshold, temp_unit_symbol


def evaluate(row, cfg, prev_row=None, rows=None):
    sym = temp_unit_symbol(cfg)
    is_rh = row.get("value_kind") == "rh"
    low_key = "bounds_low_rh" if is_rh else "bounds_low"
    high_key = "bounds_high_rh" if is_rh else "bounds_high"
    low = cfg_threshold(cfg, low_key)
    high = cfg_threshold(cfg, high_key)

    if "temp_rolling_avg" in row and row["temp_rolling_avg"] is not None:
        v = row["temp_rolling_avg"]
        kind = "avg"
    else:
        v = row.get("temp")
        kind = "raw"

    if v is None:
        return False

    if v < low or v > high:
        print(
            f"{row['ts']}  OOB {kind}  {v:.2f}  (band {low:.1f}–{high:.1f}) col={row.get('value_column')}"
        )
        return True

    return False
