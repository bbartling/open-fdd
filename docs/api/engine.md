---
title: Engine API
parent: API Reference
nav_order: 2
---

# Engine API

Programmatic API for loading rules and running FDD against pandas DataFrames.

---

## Rule loading

### load_rule

```python
from open_fdd.engine.runner import load_rule

rule = load_rule("path/to/rule.yaml")
# Returns dict with name, type, flag, inputs, params, expression
```

---

### load_rules_from_dir

```python
from open_fdd.engine.runner import load_rules_from_dir

rules = load_rules_from_dir("analyst/rules")
# Returns list of rule dicts from all *.yaml in directory
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

```python
runner.add_rule(load_rule("new_rule.yaml"))
```

---

### run

```python
result_df = runner.run(
    df,
    timestamp_col="timestamp",
    rolling_window=6,
    params={"units": "metric"},
    skip_missing_columns=False,
    column_map={"oat": "OAT (°F)", "sat": "SAT (°F)"},
)
```

| Parameter | Type | Description |
|-----------|------|-------------|
| `df` | DataFrame | Input time-series. Columns = data. |
| `timestamp_col` | str | Timestamp column (default: "timestamp") |
| `rolling_window` | int | Consecutive True samples to flag fault |
| `params` | dict | Override params (e.g. units for bounds) |
| `skip_missing_columns` | bool | Skip rules with missing columns instead of raising |
| `column_map` | dict | {rule_input: df_column}. From Brick TTL or manual. |

**Returns:** DataFrame with original columns plus fault flag columns (`*_flag`).

---

## Bounds helper

```python
from open_fdd.engine.runner import bounds_map_from_rule

rule = load_rule("sensor_bounds.yaml")
bounds = bounds_map_from_rule(rule, units="metric")
# {"Supply_Air_Temperature_Sensor": (4.0, 66.0), ...}
```

---

## Rule types

| Type | Check function | Params |
|------|----------------|--------|
| `bounds` | check_bounds | low, high; units (imperial/metric) |
| `flatline` | check_flatline | tolerance, window |
| `expression` | check_expression | (from rule) |
| `hunting` | check_hunting | delta_os_max, ahu_min_oa_dpr, window |
| `oa_fraction` | check_oa_fraction | (rule-specific) |
| `erv_efficiency` | check_erv_efficiency | (rule-specific) |
