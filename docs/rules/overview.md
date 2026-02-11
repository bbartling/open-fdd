---
title: Rules Overview
parent: Rules
nav_order: 1
---

# FDD Rules

Rules are YAML-defined checks run against time-series DataFrames. Each rule produces a boolean fault flag.

---

## Rule types

| Type | Purpose |
|------|---------|
| `bounds` | Value outside `[low, high]` |
| `flatline` | Rolling spread < tolerance (stuck sensor) |
| `hunting` | Excessive state changes (PID hunting) |
| `expression` | Custom pandas/numpy expression |
| `oa_fraction` | OA fraction vs design airflow error |
| `erv_efficiency` | ERV effectiveness out of range |

---

## YAML structure

```yaml
name: sensor_bounds
type: bounds
flag: bad_sensor
inputs:
  - oat
  - sat
params:
  low: 40
  high: 90
```

---

## Input resolution

- **Brick:** Rule inputs (e.g. `oat`) map via `ofdd:mapsToRuleInput` to `external_id`.
- **Column map:** `external_id` → DataFrame column names.
- **Fallback:** Direct `column` in YAML if no TTL mapping.

---

## Running rules

- **Platform:** FDD loop loads rules from `OFDD_DATALAKE_RULES_DIR`, runs on schedule.
- **Standalone:** `RuleRunner(rules_path=...)` or `RuleRunner(rules=[...])`; call `run(df, ...)`.

---

## Cookbook

See [Expression Rule Cookbook](expression_rule_cookbook) for AHU, chiller, weather, and advanced recipes.
