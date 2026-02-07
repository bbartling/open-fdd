---
title: Bounds Rule
nav_order: 3
---

# Bounds Rule

**Type:** `bounds` — Built-in check; no custom expression.

## What the rules engine does

The **bounds** rule flags sensor values that fall *outside* a valid range. For each input, you define `[low, high]` bounds (optionally different for imperial vs metric). The engine evaluates `(value < low) | (value > high)` — when **True**, a fault is flagged. This catches bad data, sensor drift, or physically impossible readings (e.g., SAT at 200°F when the coil can't produce that). Common sensor validation pattern.

Use `params={"units": "metric"}` at runtime to switch to metric bounds when your data is in °C, Pa, etc.

---

## bad_sensor_check (bounds)

Sensor out of range. Pass `params={"units": "metric"}` for metric bounds.

```yaml
name: bad_sensor_check
description: Returns fault if sensor is out of range
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

## Additional sensor bounds (zone, plant, IAQ)

Typical bounds for zone, plant, and IAQ sensors:

| Sensor type          | Low  | High   | Units |
|----------------------|------|--------|-------|
| Zone air temp        | 50   | 100    | °F    |
| Supply air temp      | 40   | 150    | °F    |
| CHW supply temp      | 35   | 100    | °F    |
| HW supply temp       | 50   | 212    | °F    |
| Condenser water temp | 50   | 110    | °F    |
| Relative humidity    | 0    | 100    | %     |
| CO2                  | 400  | 2000   | ppm   |
| Air pressure (inH2O)  | -5   | 10     | inH2O |

### Zone temperature bounds

```yaml
name: zone_temp_bounds
description: Zone temperature outside comfort range
type: bounds
params:
  units: imperial

flag: zone_temp_flag

inputs:
  Zone_Air_Temperature_Sensor:
    brick: Zone_Air_Temperature_Sensor
    column: zone_temp
    bounds:
      imperial: [50, 100]
      metric: [10, 38]
```

### CO2 (IAQ) bounds

```yaml
name: co2_bounds
description: CO2 concentration outside acceptable range
type: bounds
flag: co2_flag

params:
  units: imperial

inputs:
  CO2_Sensor:
    brick: CO2_Sensor
    column: co2_ppm
    bounds:
      imperial: [400, 2000]
      metric: [400, 2000]
```

### Relative humidity bounds

```yaml
name: rh_bounds
description: Relative humidity outside valid range
type: bounds
flag: rh_flag

params:
  units: imperial

inputs:
  Humidity_Sensor:
    brick: Humidity_Sensor
    column: rh_pct
    bounds:
      imperial: [0, 100]
      metric: [0, 100]
```

---

**Next:** [Flatline Rule]({{ "flatline_rule" | relative_url }})
