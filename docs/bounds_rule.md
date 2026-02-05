---
title: Bounds Rule
nav_order: 5
---

# Bounds Rule

**Type:** `bounds` — Built-in check; no custom expression.

## What the rules engine does

The **bounds** rule flags sensor values that fall *outside* a valid range. For each input, you define `[low, high]` bounds (optionally different for imperial vs metric). The engine evaluates `(value < low) | (value > high)` — when **True**, a fault is flagged. This catches bad data, sensor drift, or physically impossible readings (e.g., SAT at 200°F when the coil can't produce that). Inspired by SkySpark/Axon-style `badSensorCheck`.

Use `params={"units": "metric"}` at runtime to switch to metric bounds when your data is in °C, Pa, etc.

---

## bad_sensor_check (bounds)

Sensor out of range. Pass `params={"units": "metric"}` for metric bounds.

```yaml
name: bad_sensor_check
description: Returns fault if sensor is out of range (inspired by SkySpark badSensorCheck)
type: bounds
flag: bad_sensor_flag

params:
  units: imperial

inputs:
  Supply_Air_Temperature_Sensor:
    brick: Supply_Air_Temperature_Sensor
    column: sat
    bounds:
      imperial: [40, 150]
      metric: [4, 66]
  Return_Air_Temperature_Sensor:
    brick: Return_Air_Temperature_Sensor
    column: rat
    bounds:
      imperial: [40, 100]
      metric: [4, 38]
  Mixed_Air_Temperature_Sensor:
    brick: Mixed_Air_Temperature_Sensor
    column: mat
    bounds:
      imperial: [40, 100]
      metric: [4, 38]
  Outside_Air_Temperature_Sensor:
    brick: Outside_Air_Temperature_Sensor
    column: oat
    bounds:
      imperial: [-40, 120]
      metric: [-40, 49]
  Discharge_Air_Static_Pressure_Sensor:
    brick: Discharge_Air_Static_Pressure_Sensor
    column: ap
    bounds:
      imperial: [-5, 10]
      metric: [-1244, 2488]
```

Full rule with additional sensors in [`open_fdd/rules/sensor_bounds.yaml`](https://github.com/bbartling/open-fdd/tree/master/open_fdd/rules).

---

**Next:** [Flatline Rule]({{ "flatline_rule" | relative_url }})
