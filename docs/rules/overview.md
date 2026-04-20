---
title: Overview
parent: Fault rules for HVAC
nav_order: 1
---

# Fault rules

Fault rules are **YAML-defined** checks run against **pandas** `DataFrame`s. Each rule produces boolean fault flag columns (and related outputs) via **`RuleRunner`**.

Rules often use **Brick class names** as logical input keys; you supply a **`column_map`** from those keys to your actual DataFrame columns (dict, manifest, or custom resolver). See [Column map resolvers](../column_map_resolvers) and the [Expression rule cookbook](../expression_rule_cookbook).

---

## Where rules live

Keep rule YAML in a **single directory** (for example `my_rules/`) or pass parsed dicts to **`RuleRunner(rules=[...])`**. Example snippets live under **`examples/`** and **`open_fdd/tests/fixtures/rules/`** in this repository.

See the [Expression rule cookbook](../expression_rule_cookbook) to add or adapt rules. For how YAML becomes pandas operations, see [YAML rules → Pandas (under the hood)](pandas_yaml_dataframes).

---

## Hot reload

**`RuleRunner`** reads the rule list you give it at construction time. To pick up disk edits, call **`load_rules_from_dir`** again (or construct a new **`RuleRunner`**) before the next **`run()`**.

---

## Rule types

| Type | Purpose |
|------|---------|
| `bounds` | Value outside `[low, high]` |
| `flatline` | Rolling spread < tolerance (stuck sensor) |
| `hunting` | Excessive state changes (PID hunting) |
| `expression` | Custom pandas/numpy expression; supports schedule/weather gating via `params.schedule` and `params.weather_band` |
| `oa_fraction` | OA fraction vs design airflow error |
| `erv_efficiency` | ERV effectiveness out of range |

These six values are the built-in `type` values in the engine. **Occupied-hours and weather gating are not separate rule types**; they are optional masks injected for `type: expression` rules (`schedule_occupied`, `weather_allows_fdd`). See the [Expression rule cookbook](../expression_rule_cookbook#occupied-hours-and-weather-gating-expressions).

---

## YAML structure

Example with Brick-style logical keys (map them with **`column_map`**):

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

**Per-rule rolling window:** Set `params.rolling_window` (e.g. `6`) in a rule to require that many consecutive True samples before the fault is flagged. Omit for “flag on any True.” See fixtures such as `sensor_flatline.yaml` under **`open_fdd/tests/fixtures/rules/`**.

---

## Running rules

```python
from pathlib import Path
from open_fdd.engine.runner import RuleRunner

runner = RuleRunner(rules_path=Path("path/to/rules"))
out = runner.run(df, timestamp_col="timestamp", column_map={...})
```

---

## Engineering metadata and analytics

Downstream analytics often combine **fault flags** from **`RuleRunner`** with **equipment metadata** and **time series** you already store. For Brick / 223P graph and API workflows, see **[open-fdd-afdd-stack docs](https://github.com/bbartling/open-fdd-afdd-stack/tree/main/docs)** and [Data modeling & platform docs](../modeling/index).

---

## Cookbook

See [Expression rule cookbook](../expression_rule_cookbook) for AHU, chiller, weather, and advanced recipes.
