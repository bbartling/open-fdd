---
title: Overview
parent: Fault rules for HVAC
nav_order: 1
---

# Fault rules

Fault rules are **YAML-defined** checks run against **pandas** `DataFrame`s. Each rule produces integer fault flag columns (`0` / `1`, and related outputs) via **`RuleRunner`**.

Each rule declares **logical input names** in YAML. You supply a **`column_map`** from those names (or optional ontology keys like **Brick** class labels) to your DataFrame columns. See [Column map resolvers](../column_map_resolvers) and the [YAML expression cookbook](../expression_rule_cookbook_yaml).

---

## Where rules live

Keep rule YAML in a **single directory** (for example `my_rules/`) or pass parsed dicts to **`RuleRunner(rules=[...])`**. Example snippets live under **`examples/`** and **`open_fdd/tests/fixtures/rules/`** in this repository.

See the [YAML expression cookbook](../expression_rule_cookbook_yaml) to add or adapt rules. For how YAML becomes pandas operations, see [YAML rules → Pandas (under the hood)](pandas_yaml_dataframes).

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

These six values are the built-in `type` values in the engine. **Occupied-hours and weather gating are not separate rule types**; they are optional masks injected for `type: expression` rules (`schedule_occupied`, `weather_allows_fdd`). See the [YAML expression cookbook](../expression_rule_cookbook_yaml#occupied-hours-and-weather-gating-expressions).

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

Downstream analytics often combine **fault flags** from **`RuleRunner`** with **equipment metadata** and **time series** you already store. Use **`column_map`** to align ontology or vendor labels with DataFrame columns — see [Column maps & ontologies](../modeling/index) and [Column map resolvers](../column_map_resolvers).

---

## Cookbook

See [YAML expression cookbook](../expression_rule_cookbook_yaml) and `examples/AHU/rules/` for GL36-style recipes.
