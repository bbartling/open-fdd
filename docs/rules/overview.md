---
title: Rules Overview
parent: Rules
nav_order: 1
---

# FDD Rules

Rules are YAML-defined checks run against time-series DataFrames. Each rule produces a boolean fault flag.

---

## Where to place your rules

**One place only:** put your project rules in **`analyst/rules/`** (`.yaml` files). The FDD loop loads from this directory every run. Copy or adapt examples from `open_fdd/rules/` (sensor bounds, flatline, weather, AHU). To write new rules, see the [Expression Rule Cookbook](expression_rule_cookbook) and online docs.

Config: `rules_dir: "analyst/rules"` (or `OFDD_RULES_DIR`). If that path doesn’t exist, the loop falls back to `open_fdd/rules`.

---

## Hot reload (edit → run → view in Grafana)

1. **Edit** a rule in `analyst/rules/*.yaml` (or add a new one).
2. **Run** FDD: wait for the next scheduled run, or trigger now with `touch config/.run_fdd_now` or `POST /run-fdd` (see [Operations](howto/operations)).
3. **View** fault results in Grafana (Fault Results dashboard). No restart needed — the loop reloads all rules from disk on every run.

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
  rolling_window: 6   # optional: require N consecutive True samples before flagging
```

**Per-rule rolling window:** Set `params.rolling_window` (e.g. `6`) in a rule to require that many consecutive True samples before the fault is flagged. Omit for “flag on any True.” See `sensor_flatline.yaml`, `weather_temp_stuck.yaml`.

---

## Input resolution

- **Brick:** Rule inputs (e.g. `oat`) map via `ofdd:mapsToRuleInput` to `external_id`.
- **Column map:** `external_id` → DataFrame column names.
- **Fallback:** Direct `column` in YAML if no TTL mapping.

---

## Running rules

- **Platform:** FDD loop loads rules from `rules_dir` (default `analyst/rules`) each run; edit YAML and trigger a run to see changes in Grafana.
- **Standalone:** `RuleRunner(rules_path=...)` or `RuleRunner(rules=[...])`; call `run(df, ...)`.

---

## Cookbook

See [Expression Rule Cookbook](expression_rule_cookbook) for AHU, chiller, weather, and advanced recipes.
