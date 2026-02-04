---
title: API Reference
nav_order: 6
---

# API Reference

## RuleRunner

```python
from open_fdd import RuleRunner

runner = RuleRunner(rules_path="open_fdd/rules")
# or
runner = RuleRunner(rules=[{...}, {...}])
```

### run

```python
result = runner.run(
    df,
    timestamp_col="timestamp",
    rolling_window=None,
    params=None,
    skip_missing_columns=False,
    column_map=None,
)
```

| Arg | Type | Description |
|-----|------|-------------|
| `df` | `pd.DataFrame` | Time-series data |
| `timestamp_col` | `str` | Column with timestamps (default: `"timestamp"`) |
| `rolling_window` | `int` | Consecutive samples to flag fault (None = any) |
| `params` | `dict` | Override rule params (e.g. `{"units": "metric"}`) |
| `skip_missing_columns` | `bool` | Skip rules with missing columns |
| `column_map` | `dict` | `{BRICK_class: df_column}` or `{rule_input: df_column}`. Runner resolves via BRICK first when rule has `brick` tag. |

**Returns:** DataFrame with original columns plus fault flag columns.

---

## Reports

```python
from open_fdd.reports import summarize_fault, summarize_all_faults, print_summary
```

### summarize_fault

```python
summary = summarize_fault(
    df,
    flag_col="fc1_flag",
    timestamp_col="timestamp",
    sensor_cols={"label": "column_name"},
    motor_col="supply_vfd_speed",
)
```

**Returns:** Dict with `total_days`, `total_hours`, `hours_<flag>_mode`, `percent_true`, `percent_false`, `hours_motor_runtime`, `flag_true_<label>`.

### summarize_all_faults

```python
results = summarize_all_faults(
    df,
    flag_cols=None,
    motor_col="supply_vfd_speed",
    sensor_map=None,
)
```

**Returns:** `Dict[flag_col, summary_dict]`.

### print_summary

```python
print_summary(summary, title="FC1 Low Duct Static")
```

---

## brick_resolver

```python
from open_fdd import resolve_from_ttl

column_map = resolve_from_ttl("examples/brick_model.ttl")
# Keys: BRICK class names (Supply_Air_Temperature_Sensor, etc.) and rule_input for backward compat
# {"Supply_Air_Temperature_Sensor": "SAT (°F)", "sat": "SAT (°F)", ...}
```

Requires `pip install open-fdd[brick]`.

---

**Next:** [Data Model & Brick]({{ "data_model" | relative_url }})

