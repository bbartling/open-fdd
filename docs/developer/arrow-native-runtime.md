---
title: Arrow-native runtime
parent: Developer
nav_order: 3
---

# Arrow-native runtime

Open-FDD 3.0 executes Rule Lab rules on **PyArrow tables** end to end.

```
feather_store.read_site_table()
  → fdd_runner / playground.run_arrow_table()
  → apply_faults_arrow(table, cfg, context)
  → pyarrow.compute masks
```

## Authoring contract

```python
import pyarrow.compute as pc

def apply_faults_arrow(table, cfg, context=None):
    return pc.greater(table["zone_temp"], cfg["max_zone_temp"])
```

Cookbook helpers: `open_fdd.arrow_runtime.cookbook` (flatline, spread, OOB, after-hours fan).

Script-mode analytics rules receive `table` (PyArrow) and `cfg` in the sandbox — not pandas DataFrames.

## Package layout

| Module | Role |
|--------|------|
| `open_fdd.arrow_runtime.backend` | Execute rule code, batch chunks |
| `open_fdd.arrow_runtime.cookbook` | Shared fault masks |
| `open_fdd.arrow_runtime.windows` | Rolling min/max, consecutive-true |
| `open_fdd.playground.arrow_templates` | Rule Lab starter templates |
