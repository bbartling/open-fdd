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
| [Windowing & debugging](windowing-debugging) | Rolling windows, batch runtime, Rule Lab console |

All expression rules are **PyArrow columnar** — no YAML rule files, no pandas DataFrames in Rule Lab.

Future graph ML (sklearn / PyG) runs in a separate training service — see [GitHub issue #211](https://github.com/bbartling/open-fdd/issues/211).

```python
import pyarrow.compute as pc

def apply_faults_arrow(table, cfg, context=None):
    return pc.greater(table["zone_temp"], cfg["max_zone_temp"])
```
