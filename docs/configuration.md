---
title: Configuration
nav_order: 14
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

Use **BRICK class names** as input keys for Brick model compatibility. The input key is the variable name in the expression:

```yaml
name: my_rule
type: expression
flag: my_flag

inputs:
  Supply_Air_Temperature_Sensor:
    brick: Supply_Air_Temperature_Sensor
    column: sat
  Supply_Air_Temperature_Setpoint:
    brick: Supply_Air_Temperature_Setpoint
    column: sat_setpoint

params:
  err_thres: 1.0

expression: |
  (Supply_Air_Temperature_Sensor < Supply_Air_Temperature_Setpoint - err_thres) & (Supply_Air_Temperature_Sensor > 0)
```

When using a Brick TTL, `column_map` keys are BRICK class names; the runner resolves columns from the model.

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
flag: rule_g_flag
equipment_type: [AHU, VAV_AHU]

inputs:
  Outside_Air_Temperature_Sensor:
    brick: Outside_Air_Temperature_Sensor
    column: oat
  Supply_Air_Temperature_Setpoint:
    brick: Supply_Air_Temperature_Setpoint
    column: sat_setpoint
  Damper_Position_Command:
    brick: Damper_Position_Command
    column: economizer_sig
```

- **`brick`** — Brick class name. Used for column resolution: `column_map` can be keyed by Brick class (e.g. `Supply_Air_Temperature_Sensor`), and the runner resolves columns via BRICK first. When the same Brick class appears multiple times (e.g. two `Valve_Command`), use `BrickClass|rule_input` in the column map.
- **`equipment_type`** — Equipment types this rule applies to. When using `run_all_rules_brick.py` with a Brick TTL, only rules whose `equipment_type` matches the model's `ofdd:equipmentType` are run. See [Data Model & Brick]({{ "data_model" | relative_url }}).

---

**Next:** [API Reference]({{ "api_reference" | relative_url }}) — RuleRunner, brick_resolver, example scripts
