---
title: Rule Lab
parent: Operator Bridge
nav_order: 2
---

# Rule Lab

Rule Lab authors **Arrow-native** Python rules against the feather historian. Rules define:

```python
import pyarrow.compute as pc

def apply_faults_arrow(table, cfg, context=None):
    return pc.greater(table["zone_temp"], cfg["max_zone_temp"])
```

The bridge detects `apply_faults_arrow`, runs rules on **PyArrow tables** via `open_fdd.arrow_runtime`, and persists `.py` sources under `workspace/data/rules_py/`.

- **Quick test** — `POST /api/playground/test-rule` (returns `backend: arrow`, `ms`, flagged count)
- **Batch** — `POST /api/rules/batch` / `openfdd-fdd-loop` timer
- **Templates** — `GET /api/playground/arrow-templates`

Pin points to rules via **Model & assignments** (`/model`) commissioning JSON or BACnet tree right-click.
