---
title: Expression Rule Cookbook
nav_order: 5
---

# Expression Rule Cookbook

All fault rules in **open-fdd** with full YAML. Copy from the browser into your project — create a folder like `my_rules` on your desktop, save each rule as a `.yaml` file, and run the tutorial from there. Rules also live in [`open_fdd/rules/`](https://github.com/bbartling/open-fdd/tree/master/open_fdd/rules).

**Rule types:** `bounds` · `flatline` · `expression` · `hunting` · `oa_fraction` · `erv_efficiency`

---

## Sensor checks (bounds & flatline)

### bad_sensor_check (bounds)

Sensor out of range. Pass `params={"units": "metric"}` for metric bounds.

```yaml
# Sensor bounds — SkySpark/Axon-style
# column_map keys: Brick class names or rule input names
name: bad_sensor_check
description: Returns fault if sensor is out of range (inspired by SkySpark badSensorCheck)
type: bounds
flag: bad_sensor_flag

params:
  units: imperial

inputs:
  supply_air_temp:
    brick: Supply_Air_Temperature_Sensor
    column: sat
    bounds:
      imperial: [40, 150]
      metric: [4, 66]
  return_air_temp:
    brick: Return_Air_Temperature_Sensor
    column: rat
    bounds:
      imperial: [40, 100]
      metric: [4, 38]
  mixed_air_temp:
    brick: Mixed_Air_Temperature_Sensor
    column: mat
    bounds:
      imperial: [40, 100]
      metric: [4, 38]
  outdoor_air_temp:
    brick: Outside_Air_Temperature_Sensor
    column: oat
    bounds:
      imperial: [-40, 120]
      metric: [-40, 49]
  air_pressure_inh2o:
    column: ap
    bounds:
      imperial: [-5, 10]
      metric: [-1244, 2488]
```

### sensor_flatline (flatline)

Stuck sensor — value does not change over window.

```yaml
name: sensor_flatline
description: Fault if sensor value does not change over window (stuck sensor)
type: flatline
flag: flatline_flag

inputs:
  supply_air_temp:
    brick: Supply_Air_Temperature_Sensor
    column: sat
  zone_temp:
    brick: Zone_Temperature_Sensor
    column: zt

params:
  tolerance: 0.000001
  window: 12
```

---

## AHU fault conditions (FC1–FC16)

### FC1 — low_duct_static_at_max_fan (expression)

Duct static pressure too low with supply fan at max speed. VAV only.

```yaml
name: low_duct_static_at_max_fan
description: Duct static pressure too low with supply fan at max speed
type: expression
flag: fc1_flag
equipment_type: [VAV_AHU]

inputs:
  duct_static:
    brick: Supply_Air_Static_Pressure_Sensor
    column: duct_static
  duct_static_setpoint:
    brick: Supply_Air_Static_Pressure_Setpoint
    column: duct_static_setpoint
  supply_vfd_speed:
    brick: Supply_Fan_Speed_Command
    column: supply_vfd_speed

params:
  static_err_thres: 0.1
  vfd_max: 0.95
  vfd_err_thres: 0.05

expression: |
  (duct_static < duct_static_setpoint - static_err_thres) & (supply_vfd_speed >= vfd_max - vfd_err_thres)
```

### FC2 — mix_temp_too_low (expression)

Mix temperature too low; should be between outside and return air.

```yaml
name: mix_temp_too_low
description: Mix temperature too low; should be between outside and return air
type: expression
flag: fc2_flag
equipment_type: [AHU, VAV_AHU]

inputs:
  mat:
    brick: Mixed_Air_Temperature_Sensor
    column: mat
  rat:
    brick: Return_Air_Temperature_Sensor
    column: rat
  oat:
    brick: Outside_Air_Temperature_Sensor
    column: oat
  supply_vfd_speed:
    brick: Supply_Fan_Speed_Command
    column: supply_vfd_speed

params:
  mix_err_thres: 1.0
  return_err_thres: 1.0
  outdoor_err_thres: 1.0

expression: |
  (mat - mix_err_thres < np.minimum(rat - return_err_thres, oat - outdoor_err_thres)) & (supply_vfd_speed > 0.01)
```

### FC3 — mix_temp_too_high (expression)

Mix temperature too high; should be between outside and return air.

```yaml
name: mix_temp_too_high
description: Mix temperature too high; should be between outside and return air
type: expression
flag: fc3_flag
equipment_type: [AHU, VAV_AHU]

inputs:
  mat:
    brick: Mixed_Air_Temperature_Sensor
    column: mat
  rat:
    brick: Return_Air_Temperature_Sensor
    column: rat
  oat:
    brick: Outside_Air_Temperature_Sensor
    column: oat
  supply_vfd_speed:
    brick: Supply_Fan_Speed_Command
    column: supply_vfd_speed

params:
  mix_err_thres: 1.0
  return_err_thres: 1.0
  outdoor_err_thres: 1.0

expression: |
  (mat - mix_err_thres > np.maximum(rat + return_err_thres, oat + outdoor_err_thres)) & (supply_vfd_speed > 0.01)
```

### FC4 — excessive_ahu_state_changes (hunting)

Excessive AHU operating state changes (PID hunting).

```yaml
name: excessive_ahu_state_changes
description: Excessive AHU operating state changes detected (hunting behavior)
type: hunting
flag: fc4_flag
equipment_type: [AHU, VAV_AHU]

inputs:
  economizer_sig:
    brick: Damper_Position_Command
    column: economizer_sig
  supply_vfd_speed:
    brick: Supply_Fan_Speed_Command
    column: supply_vfd_speed
  heating_sig:
    brick: Valve_Command
    column: heating_sig
  cooling_sig:
    brick: Valve_Command
    column: cooling_sig

params:
  delta_os_max: 10
  ahu_min_oa_dpr: 0.1
  window: 60
```

### FC5 — sat_too_low_heating_mode (expression)

SAT too low in heating mode (broken heating valve).

```yaml
name: sat_too_low_heating_mode
description: SAT too low; should be higher than MAT in heating mode (broken heating valve)
type: expression
flag: fc5_flag
equipment_type: [AHU, VAV_AHU]

inputs:
  mat:
    brick: Mixed_Air_Temperature_Sensor
    column: mat
  sat:
    brick: Supply_Air_Temperature_Sensor
    column: sat
  heating_sig:
    brick: Valve_Command
    column: heating_sig
  supply_vfd_speed:
    brick: Supply_Fan_Speed_Command
    column: supply_vfd_speed

params:
  mix_err_thres: 1.0
  supply_err_thres: 1.0
  delta_t_supply_fan: 0.5

expression: |
  (sat + supply_err_thres <= mat - mix_err_thres + delta_t_supply_fan) & (heating_sig > 0.01) & (supply_vfd_speed > 0.01)
```

### FC6 — oa_fraction_airflow_error (oa_fraction)

OA fraction calc error or AHU not maintaining design airflow.

```yaml
name: oa_fraction_airflow_error
description: OA fraction calc error or AHU not maintaining design airflow in non-economizer modes
type: oa_fraction
flag: fc6_flag
equipment_type: [AHU, VAV_AHU]

inputs:
  supply_fan_air_volume:
    brick: Supply_Fan_Air_Flow_Sensor
    column: supply_fan_air_volume
  mat:
    brick: Mixed_Air_Temperature_Sensor
    column: mat
  oat:
    brick: Outside_Air_Temperature_Sensor
    column: oat
  rat:
    brick: Return_Air_Temperature_Sensor
    column: rat
  supply_vfd_speed:
    brick: Supply_Fan_Speed_Command
    column: supply_vfd_speed
  economizer_sig:
    brick: Damper_Position_Command
    column: economizer_sig
  heating_sig:
    brick: Valve_Command
    column: heating_sig
  cooling_sig:
    brick: Valve_Command
    column: cooling_sig

params:
  airflow_err_thres: 0.1
  ahu_min_oa_cfm_design: 1000.0
  oat_rat_delta_min: 5.0
  ahu_min_oa_dpr: 0.1
```

### FC7 — sat_too_low_full_heating (expression)

Supply air temp too low when heating valve fully open.

```yaml
name: sat_too_low_full_heating
description: Supply air temperature too low in full heating mode with heating valve fully open
type: expression
flag: fc7_flag
equipment_type: [AHU, VAV_AHU]

inputs:
  sat:
    brick: Supply_Air_Temperature_Sensor
    column: sat
  sat_setpoint:
    brick: Supply_Air_Temperature_Setpoint
    column: sat_setpoint
  heating_sig:
    brick: Valve_Command
    column: heating_sig
  supply_vfd_speed:
    brick: Supply_Fan_Speed_Command
    column: supply_vfd_speed

params:
  supply_err_thres: 1.0

expression: |
  (sat < sat_setpoint - supply_err_thres) & (heating_sig > 0.9) & (supply_vfd_speed > 0)
```

### FC8 — sat_mat_mismatch_economizer (expression)

SAT and MAT should be approx equal in economizer mode.

```yaml
name: sat_mat_mismatch_economizer
description: Supply air and mixed air temp should be approx equal in economizer mode
type: expression
flag: fc8_flag
equipment_type: [AHU, VAV_AHU]

inputs:
  mat:
    brick: Mixed_Air_Temperature_Sensor
    column: mat
  sat:
    brick: Supply_Air_Temperature_Sensor
    column: sat
  economizer_sig:
    brick: Damper_Position_Command
    column: economizer_sig
  cooling_sig:
    brick: Valve_Command
    column: cooling_sig

params:
  delta_t_supply_fan: 0.5
  mix_err_thres: 1.0
  supply_err_thres: 1.0
  ahu_min_oa_dpr: 0.1

expression: |
  (np.abs(sat - delta_t_supply_fan - mat) > np.sqrt(supply_err_thres**2 + mix_err_thres**2)) & (economizer_sig > ahu_min_oa_dpr) & (cooling_sig < 0.1)
```

### FC9 — oat_too_high_free_cooling (expression)

OAT too high in free cooling without mechanical cooling.

```yaml
name: oat_too_high_free_cooling
description: Outside air temp too high in free cooling without mechanical cooling
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
  cooling_sig:
    brick: Valve_Command
    column: cooling_sig

params:
  outdoor_err_thres: 1.0
  delta_t_supply_fan: 0.5
  supply_err_thres: 1.0
  ahu_min_oa_dpr: 0.1

expression: |
  (oat - outdoor_err_thres > sat_setpoint - delta_t_supply_fan + supply_err_thres) & (economizer_sig > ahu_min_oa_dpr) & (cooling_sig < 0.1)
```

### FC10 — oat_mat_mismatch_econ_mech (expression)

OAT and MAT approx equal in economizer + mechanical cooling mode.

```yaml
name: oat_mat_mismatch_econ_mech
description: OAT and MAT should be approx equal in economizer + mechanical cooling mode
type: expression
flag: fc10_flag
equipment_type: [AHU, VAV_AHU]

inputs:
  oat:
    brick: Outside_Air_Temperature_Sensor
    column: oat
  mat:
    brick: Mixed_Air_Temperature_Sensor
    column: mat
  cooling_sig:
    brick: Valve_Command
    column: cooling_sig
  economizer_sig:
    brick: Damper_Position_Command
    column: economizer_sig

params:
  outdoor_err_thres: 1.0
  mix_err_thres: 1.0

expression: |
  (np.abs(mat - oat) > np.sqrt(mix_err_thres**2 + outdoor_err_thres**2)) & (cooling_sig > 0.01) & (economizer_sig > 0.9)
```

### FC11 — oat_mat_mismatch_economizer (expression)

OAT and MAT approx equal in economizer mode.

```yaml
name: oat_mat_mismatch_economizer
description: OAT and MAT should be approx equal in economizer mode
type: expression
flag: fc11_flag
equipment_type: [AHU, VAV_AHU]

inputs:
  oat:
    brick: Outside_Air_Temperature_Sensor
    column: oat
  mat:
    brick: Mixed_Air_Temperature_Sensor
    column: mat
  economizer_sig:
    brick: Damper_Position_Command
    column: economizer_sig

params:
  outdoor_err_thres: 1.0
  mix_err_thres: 1.0

expression: |
  (np.abs(mat - oat) > np.sqrt(mix_err_thres**2 + outdoor_err_thres**2)) & (economizer_sig > 0.9)
```

### FC12 — sat_too_high_cooling_modes (expression)

SAT too high in econ+mech or mech-only cooling.

```yaml
name: sat_too_high_cooling_modes
description: SAT too high; should be less than MAT in econ+mech or mech-only cooling
type: expression
flag: fc12_flag
equipment_type: [AHU, VAV_AHU]

inputs:
  sat:
    brick: Supply_Air_Temperature_Sensor
    column: sat
  mat:
    brick: Mixed_Air_Temperature_Sensor
    column: mat
  cooling_sig:
    brick: Valve_Command
    column: cooling_sig
  economizer_sig:
    brick: Damper_Position_Command
    column: economizer_sig

params:
  delta_t_supply_fan: 0.5
  mix_err_thres: 1.0
  supply_err_thres: 1.0
  ahu_min_oa_dpr: 0.1

expression: |
  (sat > mat + np.sqrt(supply_err_thres**2 + mix_err_thres**2) + delta_t_supply_fan) & (((economizer_sig > 0.9) & (cooling_sig > 0)) | ((economizer_sig <= ahu_min_oa_dpr) & (cooling_sig > 0.9)))
```

### FC13 — sat_too_high_full_cooling (expression)

SAT too high vs setpoint in full cooling mode.

```yaml
name: sat_too_high_full_cooling
description: SAT too high vs setpoint in OS3/OS4 full cooling mode
type: expression
flag: fc13_flag
equipment_type: [AHU, VAV_AHU]

inputs:
  sat:
    brick: Supply_Air_Temperature_Sensor
    column: sat
  sat_setpoint:
    brick: Supply_Air_Temperature_Setpoint
    column: sat_setpoint
  cooling_sig:
    brick: Valve_Command
    column: cooling_sig
  economizer_sig:
    brick: Damper_Position_Command
    column: economizer_sig

params:
  supply_err_thres: 1.0
  ahu_min_oa_dpr: 0.1

expression: |
  (sat > sat_setpoint + supply_err_thres) & (((economizer_sig > 0.9) & (cooling_sig > 0.9)) | ((economizer_sig <= ahu_min_oa_dpr) & (cooling_sig > 0.9)))
```

### FC14 — cooling_coil_drop_when_inactive (expression)

Temperature drop across inactive cooling coil. Requires coil entering/leaving sensors.

```yaml
name: cooling_coil_drop_when_inactive
description: Temperature drop across inactive cooling coil in heating/economizer modes
type: expression
flag: fc14_flag
equipment_type: [AHU, VAV_AHU]

inputs:
  clg_coil_enter:
    brick: Cooling_Coil_Entering_Air_Temperature_Sensor
    column: clg_coil_enter_temp
  clg_coil_leave:
    brick: Cooling_Coil_Leaving_Air_Temperature_Sensor
    column: clg_coil_leave_temp
  heating_sig:
    brick: Valve_Command
    column: heating_sig
  cooling_sig:
    brick: Valve_Command
    column: cooling_sig
  economizer_sig:
    brick: Damper_Position_Command
    column: economizer_sig

params:
  coil_enter_err_thres: 1.0
  coil_leave_err_thres: 1.0
  ahu_min_oa_dpr: 0.1

expression: |
  ((clg_coil_enter - clg_coil_leave) > np.sqrt(coil_enter_err_thres**2 + coil_leave_err_thres**2)) & (((heating_sig > 0) & (cooling_sig == 0) & (economizer_sig <= ahu_min_oa_dpr)) | ((heating_sig == 0) & (cooling_sig == 0) & (economizer_sig > ahu_min_oa_dpr)))
```

### FC15 — heating_coil_rise_when_inactive (expression)

Temperature rise across inactive heating coil. Requires coil entering/leaving sensors.

```yaml
name: heating_coil_rise_when_inactive
description: Temperature rise across inactive heating coil in econ/mech cooling modes
type: expression
flag: fc15_flag
equipment_type: [AHU, VAV_AHU]

inputs:
  htg_coil_enter:
    brick: Heating_Coil_Entering_Air_Temperature_Sensor
    column: htg_coil_enter_temp
  htg_coil_leave:
    brick: Heating_Coil_Leaving_Air_Temperature_Sensor
    column: htg_coil_leave_temp
  heating_sig:
    brick: Valve_Command
    column: heating_sig
  cooling_sig:
    brick: Valve_Command
    column: cooling_sig
  economizer_sig:
    brick: Damper_Position_Command
    column: economizer_sig

params:
  coil_enter_err_thres: 1.0
  coil_leave_err_thres: 1.0
  delta_t_supply_fan: 0.5
  ahu_min_oa_dpr: 0.1

expression: |
  ((htg_coil_leave - htg_coil_enter) > np.sqrt(coil_enter_err_thres**2 + coil_leave_err_thres**2) + delta_t_supply_fan) & (((heating_sig == 0) & (cooling_sig == 0) & (economizer_sig > ahu_min_oa_dpr)) | ((heating_sig == 0) & (cooling_sig > 0) & (economizer_sig > 0.9)) | ((heating_sig == 0) & (cooling_sig > 0) & (economizer_sig <= ahu_min_oa_dpr)))
```

### FC16 — erv_effectiveness_fault (erv_efficiency)

ERV effectiveness outside expected range. AHU with ERV only.

```yaml
name: erv_effectiveness_fault
description: ERV effectiveness outside expected range based on OAT
type: erv_efficiency
flag: fc16_flag
equipment_type: [AHU_ERV]

inputs:
  erv_oat_enter:
    brick: Outside_Air_Temperature_Sensor
    column: erv_oat_enter
  erv_oat_leaving:
    brick: Discharge_Air_Temperature_Sensor
    column: erv_oat_leaving
  erv_eat_enter:
    brick: Return_Air_Temperature_Sensor
    column: erv_eat_enter

params:
  erv_efficiency_min_heating: 0.5
  erv_efficiency_max_heating: 0.9
  erv_efficiency_min_cooling: 0.5
  erv_efficiency_max_cooling: 0.9
  oat_low_threshold: 55.0
  oat_high_threshold: 65.0
  oat_rat_delta_min: 5.0
```

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
  diff_pressure:
    column: diff_pressure
  diff_pressure_setpoint:
    column: diff_pressure_setpoint
  pump_speed:
    column: pump_speed

params:
  diff_pressure_err_thres: 2.0
  pump_speed_max: 0.95
  pump_speed_err_thres: 0.05

expression: |
  (diff_pressure < diff_pressure_setpoint - diff_pressure_err_thres) & (pump_speed >= pump_speed_max - pump_speed_err_thres)
```

### chw_flow_high_at_max_pump (expression)

Primary chilled water flow too high with pump at high speed.

```yaml
name: chw_flow_high_at_max_pump
description: Primary chilled water flow too high with pump at high speed
type: expression
flag: fc_chiller_flow_flag

inputs:
  flow:
    column: flow
  pump_speed:
    column: pump_speed

params:
  flow_error_threshold: 1000.0
  pump_speed_max: 0.95
  pump_speed_err_thres: 0.05

expression: |
  (flow > flow_error_threshold) & (pump_speed >= pump_speed_max - pump_speed_err_thres)
```

---

## Weather station

### weather_temp_stuck (flatline)

Temperature sensor stuck at near-constant value.

```yaml
name: weather_temp_stuck
description: Temperature sensor stuck at near-constant value
type: flatline
flag: fault_temp_stuck

inputs:
  temp_f:
    column: temp_f

params:
  tolerance: 0.2
  window: 6
```

### weather_temp_spike (expression)

Unrealistic temperature change between consecutive readings.

```yaml
name: weather_temp_spike
description: Unrealistic temperature change between consecutive readings
type: expression
flag: fault_temp_spike

inputs:
  temp_f:
    column: temp_f

params:
  temp_spike_f_per_hour: 15.0

expression: |
  temp_f.diff().abs() > temp_spike_f_per_hour
```

### weather_rh_out_of_range (expression)

Relative humidity outside valid range.

```yaml
name: weather_rh_out_of_range
description: Relative humidity outside valid range (sensor error or bad data)
type: expression
flag: fault_rh_out_of_range

inputs:
  rh_pct:
    column: rh_pct

params:
  rh_min: 0.0
  rh_max: 100.0

expression: |
  (rh_pct < rh_min) | (rh_pct > rh_max)
```

### weather_gust_lt_wind (expression)

Wind gust reported lower than sustained wind (sensor error).

```yaml
name: weather_gust_lt_wind
description: Wind gust reported lower than sustained wind (sensor error)
type: expression
flag: fault_gust_lt_wind

inputs:
  gust_mph:
    column: gust_mph
  wind_mph:
    column: wind_mph

expression: |
  gust_mph.notna() & wind_mph.notna() & (gust_mph < wind_mph)
```

---

**Next:** [Configuration]({{ "configuration" | relative_url }})
