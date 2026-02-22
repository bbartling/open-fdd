---
title: Overview
parent: Fault rules for HVAC
nav_order: 1
---

# Fault rules

Fault rules are YAML-defined checks run against time-series DataFrames. Each rule produces a boolean fault flag. **Open-FDD is 100% Brick-model driven:** rule inputs refer only to Brick classes; column mapping comes from the Brick TTL via SPARQL and [Brick external timeseries references](https://docs.brickschema.org/metadata/external-representations.html#timeseries) ([timeseries storage](https://docs.brickschema.org/metadata/timeseries-storage.html)), which Open-FDD embraces at the heart of FDD.

---

## Where to place your rules

**One place only:** put your project rules in **`analyst/rules/`** (`.yaml` files). The FDD loop loads from this directory every run. Copy or adapt examples from `open_fdd/rules/` (sensor bounds, flatline, weather, AHU). To write new rules, see the [Expression Rule Cookbook](expression_rule_cookbook) and online docs.

Config: `rules_dir: "analyst/rules"` (or `OFDD_RULES_DIR`). If that path doesn’t exist, the loop falls back to `open_fdd/rules`.

---

## Hot reload (edit → run → view in Grafana)

Open-FDD is **AFDD** (Automated Fault Detection and Diagnostics): rule YAML files contain the fault logic and **params** (thresholds, tolerances, windows) for tuning. The FDD maintainer edits these files as needed; the rule runner does **not** need a restart.

1. **Edit** a rule in `analyst/rules/*.yaml` (or add a new one). Change `params` (e.g. `low`, `high`, `tolerance`, `rolling_window`) to tune fault sensitivity.
2. **Run** FDD: wait for the next scheduled run (per `rule_interval_hours` and `lookback_days` in [platform config](../configuration)), or trigger now with `touch config/.run_fdd_now` or `POST /run-fdd` (see [Operations](howto/operations)).
3. **View** fault results in Grafana (build a Fault Results dashboard from the [Grafana SQL cookbook](howto/grafana_cookbook)). Every run reloads all rules from disk, so the next run uses the latest YAML and params — hot reload style.

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

Inputs use **Brick class names** only; the Brick TTL (SPARQL) resolves each to a DataFrame column via external timeseries references. No `column` in YAML.

```yaml
name: sensor_bounds
type: bounds
flag: bad_sensor
inputs:
  Outside_Air_Temperature_Sensor:
    brick: Outside_Air_Temperature_Sensor
  Supply_Air_Temperature_Sensor:
    brick: Supply_Air_Temperature_Sensor
params:
  low: 40
  high: 90
  rolling_window: 6   # optional: require N consecutive True samples before flagging
```

**Per-rule rolling window:** Set `params.rolling_window` (e.g. `6`) in a rule to require that many consecutive True samples before the fault is flagged. Omit for “flag on any True.” See `sensor_flatline.yaml`, `weather_temp_stuck.yaml`.

---

## Input resolution (100% Brick)

- **Brick TTL:** Each rule input declares a Brick class (e.g. `brick: Supply_Air_Temperature_Sensor`). The engine resolves Brick points via SPARQL to their [external timeseries reference](https://docs.brickschema.org/metadata/external-representations.html#timeseries) (`ref:TimeseriesReference` / `ref:hasTimeseriesId`), yielding the DataFrame column name. See [Brick timeseries storage](https://docs.brickschema.org/metadata/timeseries-storage.html).
- **Column map:** Built from the Brick model (e.g. `rdfs:label` or external_id) → column names; no `column` in rule YAML.

---

## Running rules

- **Platform:** FDD loop loads rules from `rules_dir` (default `analyst/rules`) each run; edit YAML and trigger a run to see changes in Grafana.
- **Standalone:** `RuleRunner(rules_path=...)` or `RuleRunner(rules=[...])`; call `run(df, ...)`.

---

## Cookbook

See [Expression Rule Cookbook](expression_rule_cookbook) for AHU, chiller, weather, and advanced recipes.
