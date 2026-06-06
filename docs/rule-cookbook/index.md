---
title: Rule Cookbook
nav_order: 7
has_children: true
---

# Rule Cookbook

Practical patterns for **Arrow-native Rule Lab** (`apply_faults_arrow`) and optional **YAML** engine rules (`pip install "open-fdd[engine]"`).

| Page | Audience |
|------|----------|
| [Arrow recipes](arrow-recipes) | **Default** — Operator Bridge Rule Lab (3.0+) |
| [Python recipes](python-recipes) | Legacy row `evaluate()` rules (`backend: legacy_row`) |
| [YAML recipes](yaml-recipes) | Offline pandas / PyPI engine |
| [Windowing and debugging](windowing-debugging) | Tuning and false positives |

## Rule anatomy (Arrow — default)

```python
import pyarrow.compute as pc

def apply_faults_arrow(table, cfg, context=None):
    return pc.greater(table["zone_temp"], cfg["max_zone_temp"])
```

- `table`: PyArrow Table from feather historian (BACnet columns + `timestamp`)
- `cfg`: thresholds from Rule Lab config panel
- Returns a boolean mask aligned to table rows

Templates: `GET /api/playground/arrow-templates` or see [Arrow-native runtime](../developer/arrow-native-runtime.md).

## Legacy row rules

Per-row `evaluate(row, cfg, …)` is **not** the default in 3.0. Use only for migrated rules with `backend: legacy_row`. See [Python recipes](python-recipes).
