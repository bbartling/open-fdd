---
title: Rule Lab
parent: Operator Bridge
nav_order: 2
---

# Rule Lab

Rule Lab authors **Arrow-native** Python rules against the feather historian. Bench rules use **module constants** at the top of `rule.py` — no browser config panel, no `config.json` in the dev kit zip.

```python
"""Bench OA-T out of bounds (Arrow)."""

import pyarrow.compute as pc

VALUE_COLUMN = "oa-t"
OAT_LOW = 68.0
OAT_HIGH = 88.0


def _kit_value_stats(table):
    vals = pc.cast(table[VALUE_COLUMN], "float64")
    print(f"rows={table.num_rows} min={pc.min(vals).as_py():.2f} max={pc.max(vals).as_py():.2f}")


def apply_faults_arrow(table, cfg, context=None):
    _kit_value_stats(table)
    vals = pc.cast(table[VALUE_COLUMN], "float64")
    return pc.or_(pc.less(vals, OAT_LOW), pc.greater(vals, OAT_HIGH))
```

## Workflow

1. **Download kit** — `rule.py`, `data.py`, `sample.feather`, `run_test.py`, `requirements.txt`
2. **Edit constants** locally (`VALUE_COLUMN`, limits, window size)
3. **Run** `pip install -r requirements.txt` then `python run_test.py`
4. **Upload** `rule.py` on Rule Lab (integrator)

Upload validation (Phase B): AST parse, forbidden imports, `apply_faults_arrow(table, cfg, context=None)` signature.

The bridge runs rules on **PyArrow tables** via `open_fdd.arrow_runtime`, and persists `.py` sources under `workspace/data/rules_py/`.

- **Quick test** — `POST /api/playground/test-rule`
- **Batch** — `POST /api/rules/batch` / `openfdd-fdd-loop` timer (chunked when lookback > 6h)
- **Templates** — `GET /api/playground/arrow-templates`

Pin points to rules via **Model & assignments** (`/model`) commissioning JSON or BACnet tree right-click.

Bench seed: `python scripts/setup_bench_afdd.py`
