---
title: Python recipes (Arrow)
parent: Rule Cookbook
nav_order: 2
---

# Python recipes (Arrow)

All Rule Lab Python rules use **`apply_faults_arrow(table, cfg, context)`** on PyArrow tables with **`pyarrow.compute`** and **module constants**.

See **[Arrow recipes]({% link rule-cookbook/arrow-recipes.md %})** for the canonical cookbook (flatline, spread, OOB, schedule faults).

Shared helpers live in `open_fdd.arrow_runtime.cookbook` and `open_fdd.arrow_runtime.windows`. For console validation, copy **`_kit_lookback_stats`** from [Lookback window helper]({% link rule-cookbook/lookback-window.md %}).

```python
from open_fdd.arrow_runtime.windows import arrow_rolling_min, arrow_rolling_max
import pyarrow.compute as pc

VALUE_COLUMN = "oa-t"
WINDOW_SAMPLES = 12
FLATLINE_TOLERANCE = 0.1

def apply_faults_arrow(table, cfg, context=None):
    vals = pc.cast(table[VALUE_COLUMN], "float64")
    spread = pc.subtract(arrow_rolling_max(vals, WINDOW_SAMPLES), arrow_rolling_min(vals, WINDOW_SAMPLES))
    return pc.less_equal(pc.abs(spread), FLATLINE_TOLERANCE)
```
