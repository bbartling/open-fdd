---
title: API Reference
nav_order: 15
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
from open_fdd.engine.brick_resolver import resolve_from_ttl, get_equipment_types_from_ttl

column_map = resolve_from_ttl("examples/brick_model.ttl")
# Keys: BRICK class names (Supply_Air_Temperature_Sensor, etc.), BrickClass|rule_input for disambiguation, rule_input for backward compat
# {"Supply_Air_Temperature_Sensor": "SAT (°F)", "Valve_Command|heating_sig": "Prht Vlv Cmd (%)", "oat": "OAT (°F)", ...}

equipment_types = get_equipment_types_from_ttl("examples/brick_model.ttl")
# ["VAV_AHU"] — used to filter rules by equipment_type
```

Requires `pip install open-fdd[brick]`.

---

## Example scripts (Brick workflow)

| Script | Description |
|--------|-------------|
| `examples/validate_data_model.py` | SPARQL prereq, column map, rules vs model check. Run before faults. |
| `examples/run_all_rules_brick.py` | Load TTL, filter rules by equipment_type, run on CSV. |
| `examples/test_sparql.py` | Raw SPARQL test against Brick TTL. |
| `examples/brick_fault_viz/run_and_viz_faults.ipynb` | Run faults + zoom in on random fault events (Jupyter). |

```bash
python examples/test_sparql.py --ttl brick_model.ttl   # Prereq: test SPARQL
python examples/validate_data_model.py                 # Validate before faults
python examples/run_all_rules_brick.py --validate-first
jupyter notebook examples/brick_fault_viz/run_and_viz_faults.ipynb
```

---

**Next:** [Home]({{ "" | relative_url }})

