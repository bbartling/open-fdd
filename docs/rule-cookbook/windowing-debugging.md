---
title: Windowing & debugging
parent: Rule Cookbook
nav_order: 4
---

# Windowing & debugging

## Rolling windows (Arrow)

Use `open_fdd.arrow_runtime.windows` for sample-based rolling min/max and consecutive-true streaks:

```python
from open_fdd.arrow_runtime.windows import arrow_rolling_min, arrow_rolling_max, arrow_consecutive_true
```

Cookbook masks (`flatline_1h_mask`, `spread_1h_mask`, `oob_mask`) default to ~12 samples (~1 h at 5 min poll).

Config keys: `flatline_window_samples`, `flatline_tolerance`, `max_spread`, `rolling_avg_minutes`, `bounds_low` / `bounds_high`.

## Rule Lab console

Quick-test and batch responses include `backend: arrow`, `ms`, and flagged row counts. Arrow summary events appear in the event console on fault hits.
