---
title: Rule Cookbook
nav_order: 4
---

# Rule Cookbook

Practical patterns for **Arrow-native Rule Lab** (`apply_faults_arrow`) on feather historian PyArrow tables — **no pandas on the IoT edge**.

| Page | Use when |
|------|----------|
| [**Python recipes (full Arrow library)**]({% link rule-cookbook/python-recipes-arrow.md %}) | **Copy-paste GL36 A–M, VAV, plant, economizer, weather** — replaces legacy YAML cookbook |
| [**Expression cookbook (Arrow-native)**]({% link rule-cookbook/expression-cookbook.md %}) | Sensor bounds, legacy→Arrow map, commissioning checklist |
| [Arrow recipes]({% link rule-cookbook/arrow-recipes.md %}) | Short templates — threshold, flatline, OOB, fan/schedule |
| [Python recipes]({% link rule-cookbook/python-recipes.md %}) | Shared `open_fdd.arrow_runtime.cookbook` imports |
| [Lookback window helper]({% link rule-cookbook/lookback-window.md %}) | `_kit_lookback_stats` — print start/stop timestamps and span |
| [Windowing & debugging]({% link rule-cookbook/windowing-debugging.md %}) | Rolling windows, batch runtime, Rule Lab console |
| [GL36 algorithm stubs]({% link rule-cookbook/gl36-algorithm-stubs.md %}) | Doc-only supervisory patterns (trim & respond, plant resets) |

Programmatic sensor defaults: `open_fdd.arrow_runtime.sensor_catalog.SENSOR_PROFILES`.

```python
import pyarrow.compute as pc
from open_fdd.arrow_runtime.cookbook import sensor_bounds_mask

def apply_faults_arrow(table, cfg, context=None):
    return sensor_bounds_mask(table, "zone_temp", cfg)  # fault_code: VAV-C
```

Future graph ML (sklearn / PyG) runs in a separate training service — see [GitHub issue #211](https://github.com/bbartling/open-fdd/issues/211).
