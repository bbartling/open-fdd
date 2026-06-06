---
title: Python recipes (Arrow)
parent: Rule Cookbook
nav_order: 2
---

# Python recipes (Arrow)

All Rule Lab Python rules use **`apply_faults_arrow(table, cfg, context)`** on PyArrow tables with **`pyarrow.compute`**.

See **[Arrow recipes](arrow-recipes)** for the canonical cookbook (flatline, spread, OOB, schedule faults).

Shared helpers live in `open_fdd.arrow_runtime.cookbook` and `open_fdd.arrow_runtime.windows`.

```python
from open_fdd.arrow_runtime.cookbook import flatline_1h_mask

def apply_faults_arrow(table, cfg, context=None):
    return flatline_1h_mask(table, cfg)
```
