---
title: Expression Rule Cookbook
nav_order: 10
---

# Expression Rule Cookbook

**About `np` in expressions:** When you see `np` in a rule (e.g. `np.maximum`, `np.abs`, `np.sqrt`), it refers to **NumPy** — the Python computing library which Pandas uses under the hood for high-performance numerical math. open-fdd injects `np` into expression evaluation automatically, so you can use NumPy functions directly in your fault logic.

---

## How to define your own expressions

Expressions are boolean (true/false) statements — when they evaluate to **True**, a fault is flagged. open-fdd evaluates expressions with **pandas** and **NumPy** under the hood: input names become pandas Series, and `np` gives you NumPy functions for vectorized math. Here's a quick guide — AI can definitely help with this, and pandas and NumPy are popular open-source libraries in the modern data science world:

1. **Choose your inputs** — Each input maps a BRICK class (or rule name) to a DataFrame column. Use `brick:` for Brick model resolution and `column:` for the raw column name. Input names become **pandas Series** in the expression (one value per row).

2. **Define params** — Thresholds and constants go in `params`. Reference them by name in the expression (e.g. `static_err_thres`, `vfd_max`).

3. **Write the expression** — Use input names and param names as variables. The expression must evaluate to a **boolean Series** (True = fault). Use `&` for AND, `|` for OR, `~` for NOT. Use `np` for NumPy functions (`np.maximum`, `np.abs`, `np.sqrt`, etc.) — they work on Series and are vectorized (no Python loops). Comparisons and logical ops produce boolean Series. You can also use pandas Series methods like `.diff()`, `.rolling()`, `.notna()` on your inputs.

4. **Example** — A simple "sensor above threshold" rule:

```yaml
name: my_custom_rule
type: expression
flag: my_fault_flag

inputs:
  Supply_Air_Temperature_Sensor:
    brick: Supply_Air_Temperature_Sensor
    column: sat

params:
  max_temp: 90.0

expression: |
  Supply_Air_Temperature_Sensor > max_temp
```

5. **Save and run** — Save as `.yaml` in your rules folder and run with `RuleRunner(rules_path="my_rules").run(df)`.


---

## AHU fault conditions for air handling units (ASHRAE Guideline 36, Fault Rules One–Fifteen)

Fault Rules One through Fifteen are defined by ASHRAE Guideline 36. open-fdd was originally based on G36 and has been expanded with BRICK terminology.

### Fault Rule One — low_duct_static_at_max_fan (expression)

Duct static pressure too low with supply fan at max speed. VAV only.

```yaml
name: low_duct_static_at_max_fan
description: Duct static pressure too low with supply fan at max speed
type: expression
flag: fc1_flag
equipment_type: [VAV_AHU]

inputs:
  Supply_Air_Static_Pressure_Sensor:
    brick: Supply_Air_Static_Pressure_Sensor
    column: duct_static
  Supply_Air_Static_Pressure_Setpoint:
    brick: Supply_Air_Static_Pressure_Setpoint
    column: duct_static_setpoint
  Supply_Fan_Speed_Command:
    brick: Supply_Fan_Speed_Command
    column: supply_vfd_speed

params:
  static_err_thres: 0.1
  vfd_max: 0.95
  vfd_err_thres: 0.05

expression: |
  (Supply_Air_Static_Pressure_Sensor < Supply_Air_Static_Pressure_Setpoint - static_err_thres) & (Supply_Fan_Speed_Command >= vfd_max - vfd_err_thres)
```

### Fault Rule Two — mix_temp_too_low (expression)

Mix temperature too low; should be between outside and return air.

```yaml
name: mix_temp_too_low
description: Mix temperature too low; should be between outside and return air
type: expression
flag: fc2_flag
equipment_type: [AHU, VAV_AHU]

inputs:
  Mixed_Air_Temperature_Sensor:
    brick: Mixed_Air_Temperature_Sensor
    column: mat
  Return_Air_Temperature_Sensor:
    brick: Return_Air_Temperature_Sensor
    column: rat
  Outside_Air_Temperature_Sensor:
    brick: Outside_Air_Temperature_Sensor
    column: oat
  Supply_Fan_Speed_Command:
    brick: Supply_Fan_Speed_Command
    column: supply_vfd_speed

params:
  mix_err_thres: 1.0
  return_err_thres: 1.0
  outdoor_err_thres: 1.0

expression: |
  (Mixed_Air_Temperature_Sensor - mix_err_thres < np.minimum(Return_Air_Temperature_Sensor - return_err_thres, Outside_Air_Temperature_Sensor - outdoor_err_thres)) & (Supply_Fan_Speed_Command > 0.01)
```

### Fault Rule Three — mix_temp_too_high (expression)

Mix temperature too high; should be between outside and return air.

```yaml
name: mix_temp_too_high
description: Mix temperature too high; should be between outside and return air
type: expression
flag: fc3_flag
equipment_type: [AHU, VAV_AHU]

inputs:
  Mixed_Air_Temperature_Sensor:
    brick: Mixed_Air_Temperature_Sensor
    column: mat
  Return_Air_Temperature_Sensor:
    brick: Return_Air_Temperature_Sensor
    column: rat
  Outside_Air_Temperature_Sensor:
    brick: Outside_Air_Temperature_Sensor
    column: oat
  Supply_Fan_Speed_Command:
    brick: Supply_Fan_Speed_Command
    column: supply_vfd_speed

params:
  mix_err_thres: 1.0
  return_err_thres: 1.0
  outdoor_err_thres: 1.0

expression: |
  (Mixed_Air_Temperature_Sensor - mix_err_thres > np.maximum(Return_Air_Temperature_Sensor + return_err_thres, Outside_Air_Temperature_Sensor + outdoor_err_thres)) & (Supply_Fan_Speed_Command > 0.01)
```

*Fault Rule Four (hunting) — see [Hunting Rule]({{ "hunting_rule" | relative_url }}).*

### Fault Rule Five — sat_too_low_heating_mode (expression)

SAT too low in heating mode (broken heating valve).

```yaml
name: sat_too_low_heating_mode
description: SAT too low; should be higher than MAT in heating mode (broken heating valve)
type: expression
flag: fc5_flag
equipment_type: [AHU, VAV_AHU]

inputs:
  Mixed_Air_Temperature_Sensor:
    brick: Mixed_Air_Temperature_Sensor
    column: mat
  Supply_Air_Temperature_Sensor:
    brick: Supply_Air_Temperature_Sensor
    column: sat
  Valve_Command:
    brick: Valve_Command
    column: heating_sig
  Supply_Fan_Speed_Command:
    brick: Supply_Fan_Speed_Command
    column: supply_vfd_speed

params:
  mix_err_thres: 1.0
  supply_err_thres: 1.0
  delta_t_supply_fan: 0.5

expression: |
  (Supply_Air_Temperature_Sensor + supply_err_thres <= Mixed_Air_Temperature_Sensor - mix_err_thres + delta_t_supply_fan) & (Valve_Command > 0.01) & (Supply_Fan_Speed_Command > 0.01)
```

*Fault Rule Six (oa_fraction) — see [OA Fraction Rule]({{ "oa_fraction_rule" | relative_url }}).*

### Fault Rule Seven — sat_too_low_full_heating (expression)

Supply air temp too low when heating valve fully open.

```yaml
name: sat_too_low_full_heating
description: Supply air temperature too low in full heating mode with heating valve fully open
type: expression
flag: fc7_flag
equipment_type: [AHU, VAV_AHU]

inputs:
  Supply_Air_Temperature_Sensor:
    brick: Supply_Air_Temperature_Sensor
    column: sat
  Supply_Air_Temperature_Setpoint:
    brick: Supply_Air_Temperature_Setpoint
    column: sat_setpoint
  Valve_Command:
    brick: Valve_Command
    column: heating_sig
  Supply_Fan_Speed_Command:
    brick: Supply_Fan_Speed_Command
    column: supply_vfd_speed

params:
  supply_err_thres: 1.0

expression: |
  (Supply_Air_Temperature_Sensor < Supply_Air_Temperature_Setpoint - supply_err_thres) & (Valve_Command > 0.9) & (Supply_Fan_Speed_Command > 0)
```

### Fault Rule Eight — sat_mat_mismatch_economizer (expression)

SAT and MAT should be approx equal in economizer mode.

```yaml
name: sat_mat_mismatch_economizer
description: Supply air and mixed air temp should be approx equal in economizer mode
type: expression
flag: fc8_flag
equipment_type: [AHU, VAV_AHU]

inputs:
  Mixed_Air_Temperature_Sensor:
    brick: Mixed_Air_Temperature_Sensor
    column: mat
  Supply_Air_Temperature_Sensor:
    brick: Supply_Air_Temperature_Sensor
    column: sat
  Damper_Position_Command:
    brick: Damper_Position_Command
    column: economizer_sig
  Valve_Command:
    brick: Valve_Command
    column: cooling_sig

params:
  delta_t_supply_fan: 0.5
  mix_err_thres: 1.0
  supply_err_thres: 1.0
  ahu_min_oa_dpr: 0.1

expression: |
  (np.abs(Supply_Air_Temperature_Sensor - delta_t_supply_fan - Mixed_Air_Temperature_Sensor) > np.sqrt(supply_err_thres**2 + mix_err_thres**2)) & (Damper_Position_Command > ahu_min_oa_dpr) & (Valve_Command < 0.1)
```

### Fault Rule Nine — oat_too_high_free_cooling (expression)

OAT too high in free cooling without mechanical cooling.

```yaml
name: oat_too_high_free_cooling
description: Outside air temp too high in free cooling without mechanical cooling
type: expression
flag: fc9_flag
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
  Valve_Command:
    brick: Valve_Command
    column: cooling_sig

params:
  outdoor_err_thres: 1.0
  delta_t_supply_fan: 0.5
  supply_err_thres: 1.0
  ahu_min_oa_dpr: 0.1

expression: |
  (Outside_Air_Temperature_Sensor - outdoor_err_thres > Supply_Air_Temperature_Setpoint - delta_t_supply_fan + supply_err_thres) & (Damper_Position_Command > ahu_min_oa_dpr) & (Valve_Command < 0.1)
```

### Fault Rule Ten — oat_mat_mismatch_econ_mech (expression)

OAT and MAT approx equal in economizer + mechanical cooling mode.

```yaml
name: oat_mat_mismatch_econ_mech
description: OAT and MAT should be approx equal in economizer + mechanical cooling mode
type: expression
flag: fc10_flag
equipment_type: [AHU, VAV_AHU]

inputs:
  Outside_Air_Temperature_Sensor:
    brick: Outside_Air_Temperature_Sensor
    column: oat
  Mixed_Air_Temperature_Sensor:
    brick: Mixed_Air_Temperature_Sensor
    column: mat
  Valve_Command:
    brick: Valve_Command
    column: cooling_sig
  Damper_Position_Command:
    brick: Damper_Position_Command
    column: economizer_sig

params:
  outdoor_err_thres: 1.0
  mix_err_thres: 1.0

expression: |
  (np.abs(Mixed_Air_Temperature_Sensor - Outside_Air_Temperature_Sensor) > np.sqrt(mix_err_thres**2 + outdoor_err_thres**2)) & (Valve_Command > 0.01) & (Damper_Position_Command > 0.9)
```

### Fault Rule Eleven — oat_mat_mismatch_economizer (expression)

OAT and MAT approx equal in economizer mode.

```yaml
name: oat_mat_mismatch_economizer
description: OAT and MAT should be approx equal in economizer mode
type: expression
flag: fc11_flag
equipment_type: [AHU, VAV_AHU]

inputs:
  Outside_Air_Temperature_Sensor:
    brick: Outside_Air_Temperature_Sensor
    column: oat
  Mixed_Air_Temperature_Sensor:
    brick: Mixed_Air_Temperature_Sensor
    column: mat
  Damper_Position_Command:
    brick: Damper_Position_Command
    column: economizer_sig

params:
  outdoor_err_thres: 1.0
  mix_err_thres: 1.0

expression: |
  (np.abs(Mixed_Air_Temperature_Sensor - Outside_Air_Temperature_Sensor) > np.sqrt(mix_err_thres**2 + outdoor_err_thres**2)) & (Damper_Position_Command > 0.9)
```

### Fault Rule Twelve — sat_too_high_cooling_modes (expression)

SAT too high in econ+mech or mech-only cooling.

```yaml
name: sat_too_high_cooling_modes
description: SAT too high; should be less than MAT in econ+mech or mech-only cooling
type: expression
flag: fc12_flag
equipment_type: [AHU, VAV_AHU]

inputs:
  Supply_Air_Temperature_Sensor:
    brick: Supply_Air_Temperature_Sensor
    column: sat
  Mixed_Air_Temperature_Sensor:
    brick: Mixed_Air_Temperature_Sensor
    column: mat
  Valve_Command:
    brick: Valve_Command
    column: cooling_sig
  Damper_Position_Command:
    brick: Damper_Position_Command
    column: economizer_sig

params:
  delta_t_supply_fan: 0.5
  mix_err_thres: 1.0
  supply_err_thres: 1.0
  ahu_min_oa_dpr: 0.1

expression: |
  (Supply_Air_Temperature_Sensor > Mixed_Air_Temperature_Sensor + np.sqrt(supply_err_thres**2 + mix_err_thres**2) + delta_t_supply_fan) & (((Damper_Position_Command > 0.9) & (Valve_Command > 0)) | ((Damper_Position_Command <= ahu_min_oa_dpr) & (Valve_Command > 0.9)))
```

### Fault Rule Thirteen — sat_too_high_full_cooling (expression)

SAT too high vs setpoint in full cooling mode.

```yaml
name: sat_too_high_full_cooling
description: SAT too high vs setpoint in OS3/OS4 full cooling mode
type: expression
flag: fc13_flag
equipment_type: [AHU, VAV_AHU]

inputs:
  Supply_Air_Temperature_Sensor:
    brick: Supply_Air_Temperature_Sensor
    column: sat
  Supply_Air_Temperature_Setpoint:
    brick: Supply_Air_Temperature_Setpoint
    column: sat_setpoint
  Valve_Command:
    brick: Valve_Command
    column: cooling_sig
  Damper_Position_Command:
    brick: Damper_Position_Command
    column: economizer_sig

params:
  supply_err_thres: 1.0
  ahu_min_oa_dpr: 0.1

expression: |
  (Supply_Air_Temperature_Sensor > Supply_Air_Temperature_Setpoint + supply_err_thres) & (((Damper_Position_Command > 0.9) & (Valve_Command > 0.9)) | ((Damper_Position_Command <= ahu_min_oa_dpr) & (Valve_Command > 0.9)))
```

### Fault Rule Fourteen — cooling_coil_drop_when_inactive (expression)

Temperature drop across inactive cooling coil. Requires coil entering/leaving sensors.

```yaml
name: cooling_coil_drop_when_inactive
description: Temperature drop across inactive cooling coil in heating/economizer modes
type: expression
flag: fc14_flag
equipment_type: [AHU, VAV_AHU]

inputs:
  Cooling_Coil_Entering_Air_Temperature_Sensor:
    brick: Cooling_Coil_Entering_Air_Temperature_Sensor
    column: clg_coil_enter_temp
  Cooling_Coil_Leaving_Air_Temperature_Sensor:
    brick: Cooling_Coil_Leaving_Air_Temperature_Sensor
    column: clg_coil_leave_temp
  Heating_Valve_Command:
    brick: Valve_Command
    column: heating_sig
  Cooling_Valve_Command:
    brick: Valve_Command
    column: cooling_sig
  Damper_Position_Command:
    brick: Damper_Position_Command
    column: economizer_sig

params:
  coil_enter_err_thres: 1.0
  coil_leave_err_thres: 1.0
  ahu_min_oa_dpr: 0.1

expression: |
  ((Cooling_Coil_Entering_Air_Temperature_Sensor - Cooling_Coil_Leaving_Air_Temperature_Sensor) > np.sqrt(coil_enter_err_thres**2 + coil_leave_err_thres**2)) & (((Heating_Valve_Command > 0) & (Cooling_Valve_Command == 0) & (Damper_Position_Command <= ahu_min_oa_dpr)) | ((Heating_Valve_Command == 0) & (Cooling_Valve_Command == 0) & (Damper_Position_Command > ahu_min_oa_dpr)))
```

### Fault Rule Fifteen — heating_coil_rise_when_inactive (expression)

Temperature rise across inactive heating coil. Requires coil entering/leaving sensors.

```yaml
name: heating_coil_rise_when_inactive
description: Temperature rise across inactive heating coil in econ/mech cooling modes
type: expression
flag: fc15_flag
equipment_type: [AHU, VAV_AHU]

inputs:
  Heating_Coil_Entering_Air_Temperature_Sensor:
    brick: Heating_Coil_Entering_Air_Temperature_Sensor
    column: htg_coil_enter_temp
  Heating_Coil_Leaving_Air_Temperature_Sensor:
    brick: Heating_Coil_Leaving_Air_Temperature_Sensor
    column: htg_coil_leave_temp
  Heating_Valve_Command:
    brick: Valve_Command
    column: heating_sig
  Cooling_Valve_Command:
    brick: Valve_Command
    column: cooling_sig
  Damper_Position_Command:
    brick: Damper_Position_Command
    column: economizer_sig

params:
  coil_enter_err_thres: 1.0
  coil_leave_err_thres: 1.0
  delta_t_supply_fan: 0.5
  ahu_min_oa_dpr: 0.1

expression: |
  ((Heating_Coil_Leaving_Air_Temperature_Sensor - Heating_Coil_Entering_Air_Temperature_Sensor) > np.sqrt(coil_enter_err_thres**2 + coil_leave_err_thres**2) + delta_t_supply_fan) & (((Heating_Valve_Command == 0) & (Cooling_Valve_Command == 0) & (Damper_Position_Command > ahu_min_oa_dpr)) | ((Heating_Valve_Command == 0) & (Cooling_Valve_Command > 0) & (Damper_Position_Command > 0.9)) | ((Heating_Valve_Command == 0) & (Cooling_Valve_Command > 0) & (Damper_Position_Command <= ahu_min_oa_dpr)))
```

*Fault Rule Sixteen (erv_efficiency, custom) — see [ERV Efficiency Rule]({{ "erv_efficiency_rule" | relative_url }}).*

---

## Chiller plant

### pump_diff_pressure_low (expression)

Variable pump does not meet differential pressure setpoint at full speed.

```yaml
name: pump_diff_pressure_low
description: Variable pump does not meet differential pressure setpoint at full speed
type: expression
flag: fc_pump_flag

inputs:
  Differential_Pressure_Sensor:
    brick: Differential_Pressure_Sensor
    column: diff_pressure
  Differential_Pressure_Setpoint:
    brick: Differential_Pressure_Setpoint
    column: diff_pressure_setpoint
  Pump_Speed_Command:
    brick: Pump_Speed_Command
    column: pump_speed

params:
  diff_pressure_err_thres: 2.0
  pump_speed_max: 0.95
  pump_speed_err_thres: 0.05

expression: |
  (Differential_Pressure_Sensor < Differential_Pressure_Setpoint - diff_pressure_err_thres) & (Pump_Speed_Command >= pump_speed_max - pump_speed_err_thres)
```

### chw_flow_high_at_max_pump (expression)

Primary chilled water flow too high with pump at high speed.

```yaml
name: chw_flow_high_at_max_pump
description: Primary chilled water flow too high with pump at high speed
type: expression
flag: fc_chiller_flow_flag

inputs:
  Water_Flow_Sensor:
    brick: Water_Flow_Sensor
    column: flow
  Pump_Speed_Command:
    brick: Pump_Speed_Command
    column: pump_speed

params:
  flow_error_threshold: 1000.0
  pump_speed_max: 0.95
  pump_speed_err_thres: 0.05

expression: |
  (Water_Flow_Sensor > flow_error_threshold) & (Pump_Speed_Command >= pump_speed_max - pump_speed_err_thres)
```

---

## Weather station

*weather_temp_stuck (flatline) — see [Flatline Rule]({{ "flatline_rule" | relative_url }}).*

### weather_temp_spike (expression)

Unrealistic temperature change between consecutive readings.

```yaml
name: weather_temp_spike
description: Unrealistic temperature change between consecutive readings
type: expression
flag: fault_temp_spike

inputs:
  Outside_Air_Temperature_Sensor:
    brick: Outside_Air_Temperature_Sensor
    column: temp_f

params:
  temp_spike_f_per_hour: 15.0

expression: |
  Outside_Air_Temperature_Sensor.diff().abs() > temp_spike_f_per_hour
```

### weather_rh_out_of_range (expression)

Relative humidity outside valid range.

```yaml
name: weather_rh_out_of_range
description: Relative humidity outside valid range (sensor error or bad data)
type: expression
flag: fault_rh_out_of_range

inputs:
  Humidity_Sensor:
    brick: Humidity_Sensor
    column: rh_pct

params:
  rh_min: 0.0
  rh_max: 100.0

expression: |
  (Humidity_Sensor < rh_min) | (Humidity_Sensor > rh_max)
```

### weather_gust_lt_wind (expression)

Wind gust reported lower than sustained wind (sensor error).

```yaml
name: weather_gust_lt_wind
description: Wind gust reported lower than sustained wind (sensor error)
type: expression
flag: fault_gust_lt_wind

inputs:
  Wind_Gust_Speed_Sensor:
    brick: Wind_Gust_Speed_Sensor
    column: gust_mph
  Wind_Speed_Sensor:
    brick: Wind_Speed_Sensor
    column: wind_mph

expression: |
  Wind_Gust_Speed_Sensor.notna() & Wind_Speed_Sensor.notna() & (Wind_Gust_Speed_Sensor < Wind_Speed_Sensor)
```



---

**Next:** [Data Model & Brick]({{ "data_model" | relative_url }}) — Brick TTL, validate, run
