---
title: Flatline Rule
nav_order: 4
---

# Flatline Rule

**Type:** `flatline` — Built-in check; no custom expression.

## What the rules engine does

The **flatline** rule flags sensors that are *stuck* — the value does not change (or changes very little) over a rolling window. The engine computes the rolling spread (max − min) over `window` samples. When the spread is below `tolerance`, a fault is flagged. This catches dead sensors, frozen readings, or communication dropouts. Inspired by SkySpark-style `hisRollup(spread, timeSensitivity) < tolerance`.

---

## sensor_flatline (flatline)

Stuck sensor — value does not change over window.

```yaml
name: sensor_flatline
description: Fault if sensor value does not change over window (stuck sensor)
type: flatline
flag: flatline_flag

inputs:
  Supply_Air_Temperature_Sensor:
    brick: Supply_Air_Temperature_Sensor
    column: sat
  Zone_Temperature_Sensor:
    brick: Zone_Temperature_Sensor
    column: zt

params:
  tolerance: 0.000001
  window: 12
```

---

## weather_temp_stuck (flatline)

Temperature sensor stuck at near-constant value. Common for weather stations.

```yaml
name: weather_temp_stuck
description: Temperature sensor stuck at near-constant value
type: flatline
flag: fault_temp_stuck

inputs:
  Outside_Air_Temperature_Sensor:
    brick: Outside_Air_Temperature_Sensor
    column: temp_f

params:
  tolerance: 0.2
  window: 6
```

---

## RH flatline

Relative humidity sensor stuck at constant value.

```yaml
name: rh_flatline
description: Humidity sensor stuck (minimal variation over window)
type: flatline
flag: rh_flatline_flag

inputs:
  Humidity_Sensor:
    brick: Humidity_Sensor
    column: rh_pct

params:
  tolerance: 0.15
  window: 12
```

---

## CO2 flatline

CO2 sensor stuck; common when sensor is offline or malfunctioning.

```yaml
name: co2_flatline
description: CO2 sensor stuck at constant value
type: flatline
flag: co2_flatline_flag

inputs:
  CO2_Sensor:
    brick: CO2_Sensor
    column: co2_ppm

params:
  tolerance: 1.0
  window: 12
```

---

**Next:** [Hunting Rule]({{ "hunting_rule" | relative_url }})
