---
title: Public API
nav_order: 1
parent: API Reference
---

# Public API

*Ground truth for open-fdd. Generated from docstrings; append to this file when adding public APIs.*

---

## open_fdd (package)

```python
from open_fdd import RuleRunner, resolve_from_ttl
```

**Exports:** `RuleRunner`, `resolve_from_ttl`

---

## open_fdd.engine

### RuleRunner

```python
from open_fdd import RuleRunner

runner = RuleRunner(rules_path="open_fdd/rules")
# or
runner = RuleRunner(rules=[load_rule("ahu_rule_a.yaml")])
```

**Constructor:**

| Arg | Type | Description |
|-----|------|-------------|
| `rules_path` | str, Path, None | Directory with .yaml rules |
| `rules` | list[dict], None | Rule dicts (alternative to path) |

**Methods:**

- **add_rule(rule: dict) → None** — Add one rule config.
- **run(df, timestamp_col=None, rolling_window=None, params=None, skip_missing_columns=False, column_map=None) → DataFrame** — Run all rules. Returns input df with added flag columns.

**run() parameters:**

| Arg | Type | Default | Description |
|-----|------|---------|-------------|
| `df` | DataFrame | — | Time-series data |
| `timestamp_col` | str, None | `"timestamp"` | Timestamp column name |
| `rolling_window` | int, None | None | Consecutive samples to flag fault |
| `params` | dict, None | None | Override rule params |
| `skip_missing_columns` | bool | False | Skip rules with missing columns |
| `column_map` | dict, None | None | {BRICK_class: df_column} or {rule_input: df_column} |

**Returns:** DataFrame with original columns + fault flag columns.

---

### load_rule

```python
from open_fdd.engine import load_rule

rule = load_rule("open_fdd/rules/ahu_rule_a.yaml")
```

**Parameters:** `path` — str or Path to .yaml file.

**Returns:** dict (parsed YAML).

---

### load_rules_from_dir

```python
from open_fdd.engine.runner import load_rules_from_dir

rules = load_rules_from_dir("open_fdd/rules")
```

**Parameters:** `path` — str or Path to directory.

**Returns:** list[dict] — All .yaml files in directory.

---

### bounds_map_from_rule

```python
from open_fdd.engine import bounds_map_from_rule

bounds = bounds_map_from_rule(rule, units="imperial")
# {brick_name: (low, high), ...}
```

**Parameters:** `rule` — dict. `units` — `"imperial"` or `"metric"`.

**Returns:** dict — {brick_name: (low, high)}.

---

### resolve_from_ttl

```python
from open_fdd.engine.brick_resolver import resolve_from_ttl

column_map = resolve_from_ttl("examples/brick_model.ttl")
```

**Parameters:** `ttl_path` — str or Path to Brick TTL.

**Returns:** dict — {BRICK_class: df_column}. For duplicates: `BrickClass|rule_input` key.

**Raises:** ImportError if rdflib not installed.

---

### get_equipment_types_from_ttl

```python
from open_fdd.engine.brick_resolver import get_equipment_types_from_ttl

types = get_equipment_types_from_ttl("examples/brick_model.ttl")
# ["VAV_AHU", ...]
```

**Parameters:** `ttl_path` — str or Path to Brick TTL.

**Returns:** list[str] — Equipment types from model.

---

## open_fdd.reports

### summarize_fault

```python
from open_fdd.reports import summarize_fault

summary = summarize_fault(
    df, flag_col="rule_a_flag",
    timestamp_col="timestamp",
    sensor_cols=None,
    motor_col=None,
    period_range=None,
)
```

**Parameters:**

| Arg | Type | Description |
|-----|------|-------------|
| `df` | DataFrame | With fault flags |
| `flag_col` | str | Flag column name |
| `timestamp_col` | str, None | Timestamp column |
| `sensor_cols` | dict, None | {label: column} for stats |
| `motor_col` | str, None | Motor runtime column |
| `period_range` | tuple, None | (start_ts, end_ts) for period |

**Returns:** dict — `total_days`, `total_hours`, `hours_*_mode`, `percent_true`, `percent_false`, `hours_motor_runtime`, `flag_true_*`.

---

### summarize_all_faults

```python
from open_fdd.reports import summarize_all_faults

results = summarize_all_faults(df, flag_cols=None, motor_col=None, sensor_map=None)
```

**Returns:** dict[flag_col, summary_dict].

---

### print_summary

```python
from open_fdd.reports import print_summary

print_summary(summary, title="Rule A (duct static)")
```

---

### get_fault_events

```python
from open_fdd.reports import get_fault_events

events = get_fault_events(df, flag_col="rule_a_flag", timestamp_col="timestamp")
# DataFrame: start, end, flag_col, duration_samples
```

---

### all_fault_events

```python
from open_fdd.reports import all_fault_events

events = all_fault_events(df, flag_cols=None, timestamp_col="timestamp")
```

**Returns:** DataFrame with all flag columns’ events.

---

### analyze_bounds_episodes, analyze_flatline_episodes

Episode analysis for bounds and flatline flags.

---

### time_range, flatline_period, flatline_period_range

Time-range helpers for fault periods.

---

### (Optional) build_report, events_from_dataframe, events_to_summary_table

Requires `python-docx`. Build Word reports from fault events.

---

## Internal (may change)

- `open_fdd.engine.checks` — check_bounds, check_expression, check_flatline, check_hunting, check_oa_fraction, check_erv_efficiency
- `open_fdd.reports.fault_viz` — plot helpers, zoom_on_event internals
