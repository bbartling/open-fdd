---
title: Fault confirmation / minimum duration
parent: Rule Cookbook
nav_order: 3
---

# Fault confirmation

A raw rule condition can flicker true for one sample. **Fault confirmation** delays the final fault mask until the condition stays true for N consecutive rows or N minutes.

## Config fields

| Field | Type | Meaning |
|-------|------|---------|
| `min_true_rows` | int | Consecutive true samples required |
| `min_elapsed_minutes` | float | Elapsed time from streak start (uses `timestamp`) |
| `poll_interval_s` | float | Fallback when timestamps missing |
| `timestamp_column` | str | Default `timestamp` |

## Example

At **60-second polling**, `min_true_rows: 5` means the condition must persist about **5 minutes** before `fault` becomes true.

PyArrow:

```python
def apply_faults_arrow(table, cfg, context=None):
    return pc.greater(table["duct-t"], 80.0)
```

Rule config:

```json
{"min_true_rows": 5, "poll_interval_s": 60}
```

DataFusion SQL (same config — confirmation runs after SQL):

```sql
SELECT
  *,
  "duct-t" > 80.0 AS fault
FROM telemetry
```

The runtime applies confirmation in `open_fdd.arrow_runtime.confirmation` for both backends.

## Paired smoke default (5 minutes)

The hardcoded paired FDD harness (`open_fdd/validation/paired_fdd_contract.py`) sets **5-minute confirmation** on every smoke rule:

```json
{"min_elapsed_minutes": 5, "min_true_rows": 5, "poll_interval_s": 60}
```

This suppresses false positives during bench 5007 / Acme OAT spread toggles. See [Paired FDD smoke](../operations/paired-fdd-smoke.md).
