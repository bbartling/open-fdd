---
title: Rule Lab
parent: Operator Bridge
nav_order: 3
---

# Rule Lab

Rule Lab is the in-browser editor for Python FDD rules. **Open-FDD 3.0** runs rules on **PyArrow Tables** by default — no per-row Python loops in the hot path.

## Contract (default — Arrow-native)

```python
import pyarrow.compute as pc

def apply_faults_arrow(table, cfg, context=None):
    return pc.greater(table["zone_temp"], cfg["max_zone_temp"])
```

- Input: `pyarrow.Table` (feather historian columns)
- Output: `pyarrow.BooleanArray` or `ChunkedArray` (same row count as input)
- Execution: columnar `pyarrow.compute` kernels + optional RecordBatch chunking

See [Arrow-native runtime](../developer/arrow-native-runtime.md) for threading env vars and batch settings.

## Legacy row rules (explicit opt-in)

Old rules using `evaluate(row, cfg, …)` still work when saved with **`"backend": "legacy_row"`** or when `OPEN_FDD_FDD_BACKEND=legacy_row` is set. New rules should use `apply_faults_arrow`.

## DataFrame scripts

Script mode (`mode: script`) is unchanged — mutate `df` and set `out = {"df": …, "events": [...]}`.

## Storage

| Artifact | Path |
|----------|------|
| Rule source | `workspace/data/rules_py/<id>.py` |
| Metadata | `workspace/data/rules_store.json` (includes `backend`) |
| Bindings | Model `fdd_input` + FDD assignments |

## Workflow

1. **Lint** — `POST /api/playground/lint` (auto-detects Arrow vs legacy)
2. **Test** — `POST /api/playground/test-rule` — returns row count, flagged count, backend, timing
3. **Templates** — `GET /api/playground/arrow-templates`
4. **Bind** — attach rule to a point in FDD assignments
5. **Batch** — `POST /api/rules/batch` or `fdd_runner` scheduled loop

Recipes: [Rule Cookbook](../rule-cookbook/). Fault codes: [Fault Codes](../fault-codes/).
