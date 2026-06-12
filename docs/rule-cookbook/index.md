---
title: Rule Cookbook
nav_order: 4
---

# Rule Cookbook

Practical patterns for **Arrow-native Rule Lab** (`apply_faults_arrow`) on feather historian PyArrow tables — **no pandas on the IoT edge**.

| Page | Use when |
|------|----------|
| [**Python recipes (full Arrow library)**]({{ "/rule-cookbook/python-recipes-arrow/" | relative_url }}) | **Copy-paste GL36 A–M, VAV, plant, economizer, weather** — replaces legacy YAML cookbook |
| [**Expression cookbook (Arrow-native)**]({{ "/rule-cookbook/expression-cookbook/" | relative_url }}) | Sensor bounds, legacy→Arrow map, commissioning checklist |
| [Arrow recipes]({{ "/rule-cookbook/arrow-recipes/" | relative_url }}) | Short templates — threshold, flatline, OOB, fan/schedule |
| [Python recipes]({{ "/rule-cookbook/python-recipes/" | relative_url }}) | Shared `open_fdd.arrow_runtime.cookbook` imports |
| [Lookback window helper]({{ "/rule-cookbook/lookback-window/" | relative_url }}) | `_kit_lookback_stats` — print start/stop timestamps and span |
| [Windowing & debugging]({{ "/rule-cookbook/windowing-debugging/" | relative_url }}) | Rolling windows, batch runtime, Rule Lab console |
| [GL36 algorithm stubs]({{ "/rule-cookbook/gl36-algorithm-stubs/" | relative_url }}) | Doc-only supervisory patterns (trim & respond, plant resets) |

Programmatic sensor defaults: `open_fdd.arrow_runtime.sensor_catalog.SENSOR_PROFILES`.

```python
import pyarrow.compute as pc
from open_fdd.arrow_runtime.cookbook import sensor_bounds_mask

def apply_faults_arrow(table, cfg, context=None):
    return sensor_bounds_mask(table, "zone_temp", cfg)  # fault_code: VAV-C
```

Future graph ML (sklearn / PyG) runs in a separate training service — see [GitHub issue #211](https://github.com/bbartling/open-fdd/issues/211).
