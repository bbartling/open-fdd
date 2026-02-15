---
title: Engine API
parent: API Reference
nav_order: 2
---

# Engine API

Programmatic Python API for loading FDD rules and running the rule engine against pandas DataFrames. Used by the platform FDD loop and by standalone scripts. Import from `open_fdd.engine.runner` and related modules.

---

## Rule loading

### load_rule

Load a single rule from a YAML file.

```python
from open_fdd.engine.runner import load_rule

rule = load_rule("path/to/rule.yaml")
# Returns dict: name, type, flag, inputs, params, expression (if expression type)
```

---

### load_rules_from_dir

Load all rules from a directory (all `*.yaml` files).

```python
from open_fdd.engine.runner import load_rules_from_dir

rules = load_rules_from_dir("analyst/rules")
# Returns list of rule dicts
```

---

## RuleRunner

### Constructor

```python
from open_fdd.engine.runner import RuleRunner

# From directory
runner = RuleRunner(rules_path="analyst/rules")

# From list of rule dicts
runner = RuleRunner(rules=[rule1, rule2, ...])
```

---

### add_rule

Append a rule to the runner.

```python
runner.add_rule(load_rule("new_rule.yaml"))
```

---

### run

Run all rules against a DataFrame. Returns the same DataFrame with added fault flag columns (`*_flag`).

```python
result_df = runner.run(
    df,
    timestamp_col="timestamp",
    rolling_window=6,   # optional global fallback; prefer params.rolling_window per rule
    params={"units": "metric"},
    skip_missing_columns=False,
    column_map={"oat": "OAT (°F)", "sat": "SAT (°F)"},
)
```

| Parameter | Type | Description |
|-----------|------|-------------|
| `df` | pandas.DataFrame | Input time-series. Columns = sensor/command data. |
| `timestamp_col` | str | Timestamp column name (default: `"timestamp"`). |
| `rolling_window` | int, optional | Global fallback for consecutive samples required to flag; overridden by per-rule `params.rolling_window`. |
| `params` | dict, optional | Override params (e.g. `units` for bounds rules). |
| `skip_missing_columns` | bool | If True, skip rules whose inputs are missing from the DataFrame instead of raising. |
| `column_map` | dict, optional | Map from rule input name to DataFrame column name (e.g. from Brick TTL). |

**Returns:** DataFrame with original columns plus fault flag columns (e.g. `flatline_flag`, `bad_sensor_flag`). Flag values are 0 or 1.

---

## Bounds helper

### bounds_map_from_rule

Build a bounds map (input → (low, high)) from a bounds rule for a given unit system.

```python
from open_fdd.engine.runner import bounds_map_from_rule

rule = load_rule("sensor_bounds.yaml")
bounds = bounds_map_from_rule(rule, units="metric")
# Returns {"Supply_Air_Temperature_Sensor": (4.0, 66.0), ...}
```

---

## Rule types

| Type | Check function | Typical params |
|------|----------------|----------------|
| `bounds` | check_bounds | low, high; units (imperial/metric) |
| `flatline` | check_flatline | tolerance, window |
| `expression` | check_expression | (from rule YAML) |
| `hunting` | check_hunting | delta_os_max, ahu_min_oa_dpr, window |
| `oa_fraction` | check_oa_fraction | (rule-specific) |
| `erv_efficiency` | check_erv_efficiency | (rule-specific) |

See [Fault rules overview](rules/overview) and the [Expression Rule Cookbook](expression_rule_cookbook) for YAML structure and examples.
