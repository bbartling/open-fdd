---
title: Rule Cookbook
nav_order: 7
has_children: true
---

# Rule Cookbook

Practical patterns for **Python Rule Lab** (`evaluate(row, cfg, …)`) and optional **YAML** engine rules (`pip install open-fdd`).

| Page | Audience |
|------|----------|
| [Python recipes](python-recipes) | Operator Bridge Rule Lab |
| [YAML recipes](yaml-recipes) | Offline pandas / PyPI engine |
| [Windowing and debugging](windowing-debugging) | Tuning and false positives |

## Rule anatomy (Python)

```python
def evaluate(row, cfg, prev_row=None, rows=None):
    # row: current sample (temp, ts_ms, rolling avg fields, …)
    # cfg: thresholds from rule config in UI
    # rows: full history in test window — use for lookbacks
    return False  # or True, or (True, window_rows)
```

Import helpers from `open_fdd.playground.cookbook` in production rules, or use site `bench_fdd_common` shims where present.
