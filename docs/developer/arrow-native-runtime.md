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

**v1 contract:** [`ArrowRuleResult`]({{ "/rule-authoring/arrow-rule-contract/" | relative_url }}) — input `pa.Table`, output boolean mask, confirmation applied by backend.

Script-mode analytics rules receive `table` (PyArrow) and `cfg` in the sandbox — not pandas DataFrames.

## PyArrow-only policy (edge + Rule Lab)

| Allowed | Forbidden |
|---------|-----------|
| `pyarrow` (`pa`), `pyarrow.compute` (`pc`) | `import pandas`, `pd.DataFrame`, `to_pandas()` |
| `open_fdd.arrow_runtime.cookbook` helpers | `import numpy` for rule logic |
| Script mode globals: `table`, `cfg`, `out` | Legacy `df` DataFrame scripts |

Rule Lab **lint** (`POST /api/playground/lint`) and rule **save** reject pandas patterns with agent-facing errors, e.g. *use `table` (PyArrow), not `df`*.

Fault rules: `apply_faults_arrow(table, cfg, context=None)`. Analytics scripts: top-level code on `table`/`cfg`, set `out = {"events": [...], "metrics": {...}}`.

## Package layout

| Module | Role |
|--------|------|
| `open_fdd.arrow_runtime.backend` | Execute rule code, batch chunks |
| `open_fdd.arrow_runtime.cookbook` | Shared fault masks |
| `open_fdd.arrow_runtime.windows` | Rolling min/max, consecutive-true |
| `open_fdd.playground.arrow_templates` | Rule Lab starter templates |
