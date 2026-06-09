---
title: Rule Cookbook
nav_order: 4
---

# Rule Cookbook

Practical patterns for **Arrow-native Rule Lab** (`apply_faults_arrow`) on feather historian PyArrow tables — **no pandas on the IoT edge**.

| Page | Use when |
|------|----------|
| [**Expression cookbook (Arrow-native)**](expression-cookbook) | **Full reference** — legacy YAML/pandas translation, sensor bounds, GL36, fault codes |
| [Arrow recipes](arrow-recipes) | Short templates — threshold, flatline, OOB, fan/schedule |
| [Python recipes](python-recipes) | Shared `open_fdd.arrow_runtime.cookbook` imports |
| [Lookback window helper](lookback-window) | `_kit_lookback_stats` — print start/stop timestamps and span |
| [Windowing & debugging](windowing-debugging) | Rolling windows, batch runtime, Rule Lab console |
| [GL36 algorithm stubs](gl36-algorithm-stubs) | Doc-only supervisory patterns (trim & respond, plant resets) |

Programmatic sensor defaults: `open_fdd.arrow_runtime.sensor_catalog.SENSOR_PROFILES`.

```python
import pyarrow.compute as pc
from open_fdd.arrow_runtime.cookbook import sensor_bounds_mask

def apply_faults_arrow(table, cfg, context=None):
    return sensor_bounds_mask(table, "zone_temp", cfg)  # fault_code: VAV-C
```

Future graph ML (sklearn / PyG) runs in a separate training service — see [GitHub issue #211](https://github.com/bbartling/open-fdd/issues/211).
