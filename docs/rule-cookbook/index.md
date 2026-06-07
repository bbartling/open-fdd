---
title: Rule Cookbook
nav_order: 4
---

# Rule Cookbook

Practical patterns for **Arrow-native Rule Lab** (`apply_faults_arrow`) on feather historian PyArrow tables.

| Page | Use when |
|------|----------|
| [Arrow recipes](arrow-recipes) | **Default** — thresholds, flatline, spread, OOB, fan/schedule faults |
| [Python recipes](python-recipes) | Same Arrow patterns with shared `open_fdd.arrow_runtime.cookbook` imports |
| [Lookback window helper](lookback-window) | `_kit_lookback_stats` — print start/stop timestamps and span |
| [Windowing & debugging](windowing-debugging) | Rolling windows, batch runtime, Rule Lab console |
| [GL36 algorithm stubs](gl36-algorithm-stubs) | Doc-only supervisory patterns (trim & respond, plant resets) |

All expression rules are **PyArrow columnar** — no YAML rule files, no pandas DataFrames in Rule Lab.

Future graph ML (sklearn / PyG) runs in a separate training service — see [GitHub issue #211](https://github.com/bbartling/open-fdd/issues/211).

```python
import pyarrow.compute as pc

def apply_faults_arrow(table, cfg, context=None):
    return pc.greater(table["zone_temp"], cfg["max_zone_temp"])
```
