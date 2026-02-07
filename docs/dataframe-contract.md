---
title: DataFrame Contract
nav_order: 22
---

# DataFrame Contract

Explicit requirements for input and output DataFrames. Use this when wiring open-fdd to your data pipeline or when an agent needs to construct valid I/O.

---

## Input DataFrame

### Required

- **Columns:** Must include all columns referenced by the rules you run. Columns are resolved via:
  - Rule `inputs.*.column` (fallback)
  - `column_map` passed to `run()` (overrides; keys = BRICK class or rule input name)
- **Dtypes:** Numeric for sensor/command columns (float or int). Boolean for status if used.

### Optional

- **timestamp_col:** Column name for timestamps (default: `"timestamp"`). Used for time-based checks (flatline window, hunting window). If absent, some rules may still run; time-ordered logic assumes rows are in chronological order.
- **Index:** Row index is not used for semantics. Order matters for rolling windows (flatline, hunting).

### Time handling

- **Order:** Rows should be chronological (ascending timestamp).
- **Sampling:** No fixed interval required; rules use sample counts (e.g. `window: 12` = 12 rows).
- **Gaps:** Gaps are allowed; rolling logic operates on consecutive rows as given.

### Units

- **Temperature:** °F (imperial) or °C (metric) — specify via `params={"units": "metric"}` for bounds rules.
- **Pressure:** inH₂O or Pa — match your data.
- **Commands/positions:** 0–1 (fraction) or 0–100 (percent) — consistent within a rule.

---

## Output DataFrame

### Added columns

- **Fault flags:** One column per rule. Name = `flag` from rule YAML.
- **Values:** Boolean. `True` = fault at that timestamp.
- **Naming:** `*_flag` convention (e.g. `rule_a_flag`, `hunting_flag`, `bad_sensor_flag`).

### Preserved

- All original columns are kept. No columns are removed.

---

## Naming conventions

| Concept | Convention | Example |
|---------|------------|---------|
| Fault flag column | `*_flag` | `rule_a_flag`, `hunting_flag` |
| Rule input (BRICK) | PascalCase | `Supply_Air_Temperature_Sensor` |
| Disambiguation | `BrickClass\|rule_input` | `Valve_Command\|heating_sig` |
| Timestamp column | `timestamp` (default) | Override via `timestamp_col` |

---

## I/O examples

### Input (minimal)

```
timestamp,duct_static,duct_static_setpoint,supply_vfd_speed
2023-01-01 00:00,0.4,0.5,0.95
2023-01-01 00:15,0.35,0.5,0.96
2023-01-01 00:30,0.3,0.5,0.97
```

### Output (after RuleRunner.run)

Same columns plus:

```
rule_a_flag
False
False
True
```

(Where `rule_a_flag` is True when duct static &lt; setpoint − margin and fan at high speed.)

### Fault counts snippet

```python
result["rule_a_flag"].sum()  # count of fault samples
result[["rule_a_flag", "rule_b_flag"]].sum()  # per-flag counts
```
