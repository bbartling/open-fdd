def evaluate(row, cfg, prev_row=None, rows=None):
    """Per-row rule: flag when SAT exceeds cfg high."""
    high = float(cfg.get("high", 75.0))
    sat = row.get("SAT") or row.get("temp")
    if sat is None:
        return False
    return float(sat) > high
