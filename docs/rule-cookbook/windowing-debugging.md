---
title: Windowing & debugging
parent: Rule Cookbook
nav_order: 4
---

# Windowing & debugging

## Lookback vs rolling window

| | **Historian lookback** | **Rolling window** |
|---|------------------------|-------------------|
| Set by | Batch `lookback_hours`, FDD loop, Quick test UI | `WINDOW_SAMPLES` constant in `rule.py` |
| Typical | 1 h scheduled; 24 h Update all | 12 samples ≈ 1 h @ 5 min poll |
| Validate with | `_kit_lookback_stats(table)` — see [Lookback window helper]({{ "/rule-cookbook/lookback-window/" | relative_url }}) | Rule logic + console `flagged` count |

## Rolling windows (Arrow)

Use `open_fdd.arrow_runtime.windows` for sample-based rolling min/max and consecutive-true streaks:

```python
from open_fdd.arrow_runtime.windows import arrow_rolling_min, arrow_rolling_max, arrow_consecutive_true
```

Cookbook masks (`flatline_1h_mask`, `spread_1h_mask`, `oob_mask`) default to ~12 samples (~1 h at 5 min poll).

Bench rules use constants: `WINDOW_SAMPLES`, `FLATLINE_TOLERANCE`, `OAT_LOW` / `OAT_HIGH`, etc. Legacy `cfg` keys still work for uploaded rules that read `cfg.get(...)`.

## Rule Lab console

Quick-test and batch responses include `backend: arrow`, `ms`, and flagged row counts. Arrow summary events appear in the event console on fault hits.
