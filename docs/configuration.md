---
title: Configuration
nav_order: 11
---

# Configuration

Rules are YAML files. Each rule has `name`, `type`, `flag`, `inputs`, and optionally `params` and `expression`.

## Rule types

| Type | Description |
|------|-------------|
| `bounds` | Value outside [low, high]; supports `units: metric` |
| `flatline` | Sensor stuck (rolling spread &lt; tolerance) |
| `expression` | Pandas/numpy expression |
| `hunting` | Excessive AHU state changes (PID hunting) |
| `oa_fraction` | OA fraction / design airflow error |
| `erv_efficiency` | ERV effectiveness out of range |

## Expression rule

```yaml
name: my_rule
type: expression
flag: my_flag

inputs:
  col_a:
    column: actual_df_column_name
  col_b:
    column: other_column

params:
  thres: 0.1

expression: |
  (col_a < col_b - thres) & (col_a > 0)
```

## Bounds rule (bad data)

Inputs use BRICK class names; `column_map` keys match:

```yaml
name: bad_sensor_check
type: bounds
flag: bad_sensor_flag

params:
  units: imperial

inputs:
  Supply_Air_Temperature_Sensor:
    brick: Supply_Air_Temperature_Sensor
    column: Supply_Air_Temperature_Sensor
    bounds:
      imperial: [40, 150]
      metric: [4, 66]
  Return_Air_Temperature_Sensor:
    brick: Return_Air_Temperature_Sensor
    column: Return_Air_Temperature_Sensor
    bounds:
      imperial: [40, 100]
      metric: [4, 38]
```

## Flatline rule

```yaml
name: sensor_flatline
type: flatline
flag: flatline_flag

inputs:
  Supply_Air_Temperature_Sensor:
    brick: Supply_Air_Temperature_Sensor
    column: Supply_Air_Temperature_Sensor
  Outside_Air_Temperature_Sensor:
    brick: Outside_Air_Temperature_Sensor
    column: Outside_Air_Temperature_Sensor

params:
  tolerance: 0.000001
  window: 12
```

## BRICK metadata in YAML

Rules can include `brick` and `equipment_type` for documentation and future filtering:

```yaml
name: oat_too_high_free_cooling
type: expression
flag: fc9_flag
equipment_type: [AHU, VAV_AHU]

inputs:
  oat:
    brick: Outside_Air_Temperature_Sensor
    column: oat
  sat_setpoint:
    brick: Supply_Air_Temperature_Setpoint
    column: sat_setpoint
  economizer_sig:
    brick: Damper_Position_Command
    column: economizer_sig
```

- **`brick`** — Brick class name. Used for column resolution: `column_map` can be keyed by Brick class (e.g. `Supply_Air_Temperature_Sensor`), and the runner resolves columns via BRICK first.
- **`equipment_type`** — Equipment types this rule applies to (for future Brick-based filtering).

---

**Next:** [API Reference]({{ "api_reference" | relative_url }})
