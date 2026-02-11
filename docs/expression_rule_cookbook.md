---
title: Expression Rule Cookbook
nav_order: 8
---

# Expression Rule Cookbook

A reference for building fault detection rules in open-fdd. Rules use **YAML** with **expression** type: when the expression evaluates to **True**, a fault is flagged. open-fdd injects **NumPy** as `np` into expression evaluation, so you can use `np.maximum`, `np.abs`, `np.sqrt`, etc. for vectorized math.

---

## BRICK naming convention

All rule inputs in this cookbook use **BRICK class names** as input keys (e.g. `Supply_Air_Temperature_Sensor`, `Mixed_Air_Temperature_Sensor`). The `column` field is the fallback DataFrame column when no `column_map` is provided. When using a Brick TTL, `column_map` keys are BRICK class names; the runner resolves each input via the model. For multiple instances of the same Brick class (e.g. heating vs cooling valve), use semantic input names (`Heating_Valve_Command`, `Cooling_Valve_Command`) with `brick: Valve_Command` and disambiguate in `column_map` with `Valve_Command|heating_sig`.

---

## How to define expressions

1. **Inputs** — Map BRICK classes or column names to DataFrame columns. Each input key becomes the variable name in the expression. Use BRICK class names as keys for Brick model compatibility.
2. **Params** — Thresholds and constants go in `params`. Reference by name (e.g. `err_thresh`, `vfd_max`).
3. **Expression** — Must evaluate to a boolean Series (True = fault). Use `&` (AND), `|` (OR), `~` (NOT). Use `.diff()`, `.rolling()`, `.notna()` for time-series logic.

**Minimal example:**

```yaml
name: high_temp_check
type: expression
flag: high_temp_flag

inputs:
  Supply_Air_Temperature_Sensor:
    brick: Supply_Air_Temperature_Sensor
    column: sat

params:
  max_temp: 90.0

expression: |
  Supply_Air_Temperature_Sensor > max_temp
```

---

## AHU rules (reference-style)

The following rules follow common industry practice for air-handling fault detection. Rules A through M are adapted from ASHRAE Guideline 36 (GL36) AFDD guidance. Thresholds and logic are tunable; adjust params for your site.

### Rule A — Duct static below setpoint at full fan speed

Static pressure under setpoint while supply fan runs near maximum. May indicate duct leakage, undersized fan, or terminal damper issues. *Adapted from GL36 AFDD guidance.*

```yaml
name: duct_static_low_at_full_speed
description: Static pressure below setpoint when fan at full speed (GL36-inspired)
type: expression
flag: rule_a_flag
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
  sp_margin: 0.12
  drv_hi_frac: 0.93
  drv_near_hi: 0.06

expression: |
  (Supply_Air_Static_Pressure_Sensor < Supply_Air_Static_Pressure_Setpoint - sp_margin) & (Supply_Fan_Speed_Command >= drv_hi_frac - drv_near_hi)
```

### Rule B — Blended air temp below expected band

Blended air temp should lie between outdoor and return. If below both (minus tolerance), suspect sensor or mixing fault. *Adapted from GL36 AFDD guidance.*

```yaml
name: blend_temp_below_band
description: Blended air temp below expected range (OAT/RAT) (GL36-inspired)
type: expression
flag: rule_b_flag
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
  blend_tol: 1.15
  rat_tol: 1.15
  oat_tol: 1.15

expression: |
  (Mixed_Air_Temperature_Sensor - blend_tol < np.minimum(Return_Air_Temperature_Sensor - rat_tol, Outside_Air_Temperature_Sensor - oat_tol)) & (Supply_Fan_Speed_Command > 0.01)
```

### Rule C — Blended air temp above expected band

Blended air temp above the higher of OAT and RAT (plus tolerance) indicates mixing or sensor fault. *Adapted from GL36 AFDD guidance.*

```yaml
name: blend_temp_above_band
description: Blended air temp above expected range (OAT/RAT) (GL36-inspired)
type: expression
flag: rule_c_flag
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
  blend_tol: 1.15
  rat_tol: 1.15
  oat_tol: 1.15

expression: |
  (Mixed_Air_Temperature_Sensor - blend_tol > np.maximum(Return_Air_Temperature_Sensor + rat_tol, Outside_Air_Temperature_Sensor + oat_tol)) & (Supply_Fan_Speed_Command > 0.01)
```

*Hunting/oscillation — see [Hunting Rule]({{ "hunting_rule" | relative_url }}).*

### Rule D — Discharge air cold when heating commanded

Discharge air temp below blended air when heating valve is open. Indicates heating coil or valve failure. *Adapted from GL36 AFDD guidance.*

```yaml
name: discharge_cold_when_heating
description: Discharge air below blended air when heating active (GL36-inspired)
type: expression
flag: rule_d_flag
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
  blend_tol: 1.15
  sat_tol: 1.15
  fan_delta_t: 0.55

expression: |
  (Supply_Air_Temperature_Sensor + sat_tol <= Mixed_Air_Temperature_Sensor - blend_tol + fan_delta_t) & (Valve_Command > 0.01) & (Supply_Fan_Speed_Command > 0.01)
```

*OA fraction — see [OA Fraction Rule]({{ "oa_fraction_rule" | relative_url }}).*

### Rule E — SAT too low with full heating

Heating valve fully open but SAT remains below setpoint. Indicates undersized coil or valve failure. *Adapted from GL36 AFDD guidance.*

```yaml
name: sat_too_low_full_heating
description: SAT below setpoint with heating valve fully open (GL36-inspired)
type: expression
flag: rule_e_flag
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

### Rule F — SAT/MAT mismatch in economizer mode

In economizer mode (min mechanical cooling), SAT should approximate MAT. Large deviation suggests coil bypass or sensor error. *Adapted from GL36 AFDD guidance.*

```yaml
name: discharge_blend_mismatch_econ
description: Discharge and blended air diverge in economizer mode (GL36-inspired)
type: expression
flag: rule_f_flag
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
  fan_delta_t: 0.55
  blend_tol: 1.15
  sat_tol: 1.15
  econ_min_open: 0.12

expression: |
  (np.abs(Supply_Air_Temperature_Sensor - fan_delta_t - Mixed_Air_Temperature_Sensor) > np.sqrt(sat_tol**2 + blend_tol**2)) & (Damper_Position_Command > econ_min_open) & (Valve_Command < 0.1)
```

### Rule G — Ambient too warm for free cooling

Outside air temperature exceeds SAT setpoint while economizer is active and mechanical cooling is off. Economizer should not be providing “free” cooling under these conditions. *Adapted from GL36 AFDD guidance.*

```yaml
name: ambient_warm_free_cool
description: Outdoor air above setpoint in free cooling mode (GL36-inspired)
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
  Valve_Command:
    brick: Valve_Command
    column: cooling_sig

params:
  oat_tol: 1.15
  fan_delta_t: 0.55
  sat_tol: 1.15
  econ_min_open: 0.12

expression: |
  (Outside_Air_Temperature_Sensor - oat_tol > Supply_Air_Temperature_Setpoint - fan_delta_t + sat_tol) & (Damper_Position_Command > econ_min_open) & (Valve_Command < 0.1)
```

### Rule H — Ambient vs blended mismatch (econ + mech cooling)

When both economizer and mechanical cooling are active, MAT should approach OAT. Large deviation suggests inadequate mixing or damper fault. *Adapted from GL36 AFDD guidance.*

```yaml
name: ambient_blend_mismatch_econ_mech
description: Outdoor and blended air diverge in econ+mech cooling (GL36-inspired)
type: expression
flag: rule_h_flag
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
  oat_tol: 1.15
  blend_tol: 1.15

expression: |
  (np.abs(Mixed_Air_Temperature_Sensor - Outside_Air_Temperature_Sensor) > np.sqrt(blend_tol**2 + oat_tol**2)) & (Valve_Command > 0.01) & (Damper_Position_Command > 0.9)
```

### Rule I — Ambient vs blended mismatch (econ-only)

In economizer-only mode, MAT should match OAT. Deviation indicates damper or mixing fault. *Adapted from GL36 AFDD guidance.*

```yaml
name: ambient_blend_mismatch_econ
description: Outdoor and blended air diverge in economizer-only mode (GL36-inspired)
type: expression
flag: rule_i_flag
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
  oat_tol: 1.15
  blend_tol: 1.15

expression: |
  (np.abs(Mixed_Air_Temperature_Sensor - Outside_Air_Temperature_Sensor) > np.sqrt(blend_tol**2 + oat_tol**2)) & (Damper_Position_Command > 0.9)
```

### Rule J — Discharge above blended in cooling

SAT exceeds MAT when cooling (econ+mech or mech-only) is active. Indicates underperforming cooling coil or valve. *Adapted from GL36 AFDD guidance.*

```yaml
name: discharge_above_blend_cooling
description: Discharge air above blended air in cooling modes (GL36-inspired)
type: expression
flag: rule_j_flag
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
  fan_delta_t: 0.55
  blend_tol: 1.15
  sat_tol: 1.15
  econ_min_open: 0.12

expression: |
  (Supply_Air_Temperature_Sensor > Mixed_Air_Temperature_Sensor + np.sqrt(sat_tol**2 + blend_tol**2) + fan_delta_t) & (((Damper_Position_Command > 0.9) & (Valve_Command > 0)) | ((Damper_Position_Command <= econ_min_open) & (Valve_Command > 0.9)))
```

### Rule K — Discharge above setpoint in full cooling

SAT above setpoint with cooling at full capacity. Suggests undersized coil or plant limits. *Adapted from GL36 AFDD guidance.*

```yaml
name: discharge_above_sp_full_cool
description: Discharge air above setpoint in full cooling mode (GL36-inspired)
type: expression
flag: rule_k_flag
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
  sat_tol: 1.15
  econ_min_open: 0.12

expression: |
  (Supply_Air_Temperature_Sensor > Supply_Air_Temperature_Setpoint + sat_tol) & (((Damper_Position_Command > 0.9) & (Valve_Command > 0.9)) | ((Damper_Position_Command <= econ_min_open) & (Valve_Command > 0.9)))
```

### Rule L — Cooling coil delta-T when inactive

Temperature drop across cooling coil when it should be off. Indicates leaking CHW valve or coil bypass. *Adapted from GL36 AFDD guidance.*

```yaml
name: clg_coil_drop_when_off
description: Temperature drop across cooling coil when it should be off (GL36-inspired)
type: expression
flag: rule_l_flag
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
  enter_tol: 1.15
  leave_tol: 1.15
  econ_min_open: 0.12

expression: |
  ((Cooling_Coil_Entering_Air_Temperature_Sensor - Cooling_Coil_Leaving_Air_Temperature_Sensor) > np.sqrt(enter_tol**2 + leave_tol**2)) & (((Heating_Valve_Command > 0) & (Cooling_Valve_Command == 0) & (Damper_Position_Command <= econ_min_open)) | ((Heating_Valve_Command == 0) & (Cooling_Valve_Command == 0) & (Damper_Position_Command > econ_min_open)))
```

### Rule M — Heating coil delta-T when inactive

Temperature rise across heating coil when it should be off. Indicates leaking HW valve. *Adapted from GL36 AFDD guidance.*

```yaml
name: htg_coil_rise_when_off
description: Temperature rise across heating coil when it should be off (GL36-inspired)
type: expression
flag: rule_m_flag
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
  enter_tol: 1.15
  leave_tol: 1.15
  fan_delta_t: 0.55
  econ_min_open: 0.12

expression: |
  ((Heating_Coil_Leaving_Air_Temperature_Sensor - Heating_Coil_Entering_Air_Temperature_Sensor) > np.sqrt(enter_tol**2 + leave_tol**2) + fan_delta_t) & (((Heating_Valve_Command == 0) & (Cooling_Valve_Command == 0) & (Damper_Position_Command > econ_min_open)) | ((Heating_Valve_Command == 0) & (Cooling_Valve_Command > 0) & (Damper_Position_Command > 0.9)) | ((Heating_Valve_Command == 0) & (Cooling_Valve_Command > 0) & (Damper_Position_Command <= econ_min_open)))
```

*Heat exchanger effectiveness — see [ERV/Heat Exchanger Rule]({{ "erv_efficiency_rule" | relative_url }}).*


---

## Central plant

### Differential pressure at max pump speed

Variable-speed pump cannot meet differential pressure setpoint at full speed. Indicates piping issues, undersized pump, or blocked strainers.

```yaml
name: dp_below_sp_pump_max
description: Differential pressure below setpoint with pump at full speed
type: expression
flag: dp_pump_flag

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
  dp_margin: 2.2
  pmp_hi_frac: 0.93
  pmp_near_hi: 0.06

expression: |
  (Differential_Pressure_Sensor < Differential_Pressure_Setpoint - dp_margin) & (Pump_Speed_Command >= pmp_hi_frac - pmp_near_hi)
```

### Plant flow high at max pump

Flow unusually high with pump at high speed. Suggests short circuit or flow meter error.

```yaml
name: flow_high_pump_max
description: Water flow unusually high with pump at full speed
type: expression
flag: flow_high_flag

inputs:
  Water_Flow_Sensor:
    brick: Water_Flow_Sensor
    column: flow
  Pump_Speed_Command:
    brick: Pump_Speed_Command
    column: pump_speed

params:
  flow_hi_limit: 1100.0
  pmp_hi_frac: 0.93
  pmp_near_hi: 0.06

expression: |
  (Water_Flow_Sensor > flow_hi_limit) & (Pump_Speed_Command >= pmp_hi_frac - pmp_near_hi)
```

### Plant supply temp outside deadband

CHW supply temperature outside deadband while pump runs. Requires coil entering/leaving or plant supply temp sensors.

```yaml
name: plant_supply_temp_deadband
description: Supply water temp outside deadband during pump operation
type: expression
flag: chw_temp_fault

inputs:
  Chilled_Water_Supply_Temperature_Sensor:
    brick: Chilled_Water_Supply_Temperature_Sensor
    column: chw_supply_temp
  Chilled_Water_Supply_Temperature_Setpoint:
    brick: Chilled_Water_Supply_Temperature_Setpoint
    column: chw_supply_sp
  Pump_Speed_Command:
    brick: Pump_Speed_Command
    column: pump_speed

params:
  sp_band: 2.2

expression: |
  (Pump_Speed_Command > 0.01) & ((Chilled_Water_Supply_Temperature_Sensor < Chilled_Water_Supply_Temperature_Setpoint - sp_band) | (Chilled_Water_Supply_Temperature_Sensor > Chilled_Water_Supply_Temperature_Setpoint + sp_band))
```

### Chiller runtime over daily limit

Chiller running beyond a daily threshold (e.g. 23 hours). Often indicates over-cooling or schedules that bypass lockout. Use a rolling window sized for your data interval (e.g. 5‑min data → 276 samples ≈ 23 h).

```yaml
name: chiller_excessive_runtime
description: Chiller runtime exceeds daily threshold (rolling window)
type: expression
flag: chiller_runtime_fault

inputs:
  Chiller_Status:
    brick: Chiller_Status
    column: chiller_run

params:
  # For 5-min data: 23 hours ≈ 276 samples; max_runtime = count of "on" samples in window
  rolling_samples: 276
  max_runtime_samples: 264

expression: |
  Chiller_Status.rolling(window=rolling_samples).sum() > max_runtime_samples
```

*Note: Adjust `rolling_samples` and `max_runtime_samples` for your data interval. For 5‑min data, 264 samples ≈ 22 hours.*

---

## Heat pumps

### Discharge cold when heating

Discharge air temperature below minimum (e.g. 80°F) when the supply fan is running. Indicates the heat pump is not heating effectively—compressor, refrigerant, or reversing valve issues. Tunable via `min_discharge_temp`. Heat pump not heating: fan on + zone cold (heating mode) but discharge still cold Zone temp < 69°F = heating mode; discharge should be warm when heating

```yaml

name: hp_discharge_cold_when_heating
description: Discharge air below minimum when fan on and zone is cold (heating mode)
type: expression
flag: hp_discharge_cold_flag
equipment_type: [Heat_Pump]

inputs:
  Supply_Air_Temperature_Sensor:
    brick: Supply_Air_Temperature_Sensor
    column: sat
  Zone_Temperature_Sensor:
    brick: Zone_Temperature_Sensor
    column: zt
  Supply_Fan_Status:
    brick: Supply_Fan_Status
    column: fan_status

params:
  min_discharge_temp: 85
  zone_cold_threshold: 69.0   # zone < 69 = heating mode
  fan_on_threshold: 0.01

expression: |
  (Supply_Fan_Status > fan_on_threshold) & (Zone_Temperature_Sensor < zone_cold_threshold) & (Supply_Air_Temperature_Sensor < min_discharge_temp)

```

---

## VAV zones

### Excessive heating during warm weather

Reheat valve open when outdoor air is warm. Suggests over-cooling or setpoint issues.

```yaml
name: zone_reheat_warm_ambient
description: Heating valve open when OAT is high
type: expression
flag: excessive_heating_flag
equipment_type: [VAV]

inputs:
  Outside_Air_Temperature_Sensor:
    brick: Outside_Air_Temperature_Sensor
    column: oat
  Reheat_Valve_Command:
    brick: Valve_Command
    column: reheat_sig

params:
  t_amb_cutoff: 78.0
  reheat_open_min: 0.52

expression: |
  (Outside_Air_Temperature_Sensor > t_amb_cutoff) & (Reheat_Valve_Command > reheat_open_min)
```

### Damper or valve at full open

Damper or reheat valve consistently at full open. Indicates override, undersized equipment, or control fault.

```yaml
name: zone_damper_valve_full_open
description: Damper or valve at full open for extended period
type: expression
flag: damper_100_flag
equipment_type: [VAV]

inputs:
  Damper_Position_Command:
    brick: Damper_Position_Command
    column: damper_pos

params:
  full_open_pct: 97.5
  roll_samples: 105

expression: |
  (Damper_Position_Command > full_open_pct) & (Damper_Position_Command.rolling(roll_samples).min() > full_open_pct)
```

### Zone and IAQ bounds

For CO2 and zone temperature out-of-range checks, use the [Bounds Rule]({{ "bounds_rule" | relative_url }}) — `co2_bounds` and `zone_temp_bounds` examples.

---

## Opportunistic rules (economizer & ventilation)

### Economizing when outdoor conditions are unfavorable

Economizer active when outdoor air is too warm or humid. Use OAT (or enthalpy if available) vs. threshold.

```yaml
name: econ_active_warm_ambient
description: OA damper open when outdoor conditions do not favor economizing
type: expression
flag: econ_when_shouldnt_flag
equipment_type: [AHU, VAV_AHU]

inputs:
  Outside_Air_Temperature_Sensor:
    brick: Outside_Air_Temperature_Sensor
    column: oat
  Damper_Position_Command:
    brick: Damper_Position_Command
    column: economizer_sig

params:
  t_amb_econ_cutoff: 63.0
  dpr_econ_min: 0.42

expression: |
  (Outside_Air_Temperature_Sensor > t_amb_econ_cutoff) & (Damper_Position_Command > dpr_econ_min)
```

### Mechanical cooling when econ could suffice

Cooling valve open when outdoor air is cool enough for economizer. Opportunity to reduce mechanical cooling.

```yaml
name: mech_cool_when_econ_available
description: Mechanical cooling active when economizing could suffice
type: expression
flag: cooling_when_econ_flag
equipment_type: [AHU, VAV_AHU]

inputs:
  Outside_Air_Temperature_Sensor:
    brick: Outside_Air_Temperature_Sensor
    column: oat
  Damper_Position_Command:
    brick: Damper_Position_Command
    column: economizer_sig
  Valve_Command:
    brick: Valve_Command
    column: cooling_sig

params:
  t_amb_econ_cutoff: 63.0
  dpr_not_econ_max: 0.32

expression: |
  (Outside_Air_Temperature_Sensor < t_amb_econ_cutoff) & (Damper_Position_Command < dpr_not_econ_max) & (Valve_Command > 0.01)
```

### Low ventilation (estimated OA fraction)

For units without airflow meters, estimate OA fraction from OAT, MAT, RAT. Flag when below minimum design OA.

```yaml
name: low_oa_fraction_estimated
description: Estimated OA fraction below minimum (OAT, MAT, RAT method)
type: expression
flag: low_vent_flag
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
  oa_min_pct: 21.0
  t_rat_oat_min_gap: 2.2

expression: |
  (Supply_Fan_Speed_Command > 0.01) & (np.abs(Return_Air_Temperature_Sensor - Outside_Air_Temperature_Sensor) > t_rat_oat_min_gap) & (((Mixed_Air_Temperature_Sensor - Return_Air_Temperature_Sensor) / (Outside_Air_Temperature_Sensor - Return_Air_Temperature_Sensor) * 100) < oa_min_pct)
```

*Note: Guard against division-by-zero when outdoor and return temps are close.*

### Preheat over-conditioning

Preheat coil leaving temp higher than needed (e.g. above OAT when OAT > SAT SP, or above SAT SP when OAT < SAT SP). Indicates wasted heating energy.

```yaml
name: preheat_excess_temp
description: Preheat coil leaving temp above required level
type: expression
flag: preheat_waste_flag
equipment_type: [AHU, VAV_AHU]

inputs:
  Preheat_Coil_Leaving_Air_Temperature_Sensor:
    brick: Preheat_Coil_Leaving_Air_Temperature_Sensor
    column: preheat_temp
  Supply_Air_Temperature_Setpoint:
    brick: Supply_Air_Temperature_Setpoint
    column: sat_setpoint
  Outside_Air_Temperature_Sensor:
    brick: Outside_Air_Temperature_Sensor
    column: oat
  Valve_Command:
    brick: Valve_Command
    column: heating_sig

params:
  excess_tol: 2.2

expression: |
  (Valve_Command > 0.01) & (((Outside_Air_Temperature_Sensor > Supply_Air_Temperature_Setpoint) & (Preheat_Coil_Leaving_Air_Temperature_Sensor - Outside_Air_Temperature_Sensor > excess_tol)) | ((Outside_Air_Temperature_Sensor < Supply_Air_Temperature_Setpoint) & (Preheat_Coil_Leaving_Air_Temperature_Sensor - Supply_Air_Temperature_Setpoint > excess_tol)))
```

### Blended air damper deviation

Expected MAT (from OAT, RAT, damper positions) differs from measured MAT. Indicates damper leakage or faulty mixing.

*Requires airflow or damper position data; logic is more involved. A simplified version compares MAT to a weighted blend of OAT and RAT when dampers suggest significant OA.*

---

## Weather station

*weather_temp_stuck (flatline) — see [Flatline Rule]({{ "flatline_rule" | relative_url }}).*

### Unrealistic temperature spike

Temperature change between consecutive readings exceeds physical limit.

```yaml
name: weather_temp_spike
description: Unrealistic temperature change between readings
type: expression
flag: fault_temp_spike

inputs:
  Outside_Air_Temperature_Sensor:
    brick: Outside_Air_Temperature_Sensor
    column: temp_f

params:
  spike_limit: 16.0

expression: |
  Outside_Air_Temperature_Sensor.diff().abs() > spike_limit
```

### RH bounds

For relative humidity out-of-range, use the [Bounds Rule]({{ "bounds_rule" | relative_url }}) — `rh_bounds` example.

### Wind gust vs sustained

```yaml
name: weather_gust_lt_wind
description: Wind gust reported lower than sustained wind
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

## Sensor validation (bounds & flatline)

Use the [Bounds Rule]({{ "bounds_rule" | relative_url }}) and [Flatline Rule]({{ "flatline_rule" | relative_url }}) for generic sensor checks. Typical bounds:

| Sensor type        | Min   | Max    |
|--------------------|-------|--------|
| Zone temp          | 40    | 100    |
| Supply air temp    | 40    | 150    |
| Air pressure (inH2O)| -5   | 10     |
| RH                 | 0     | 100    |
| Chilled water temp | 35    | 100    |
| Hot water temp     | 50    | 212    |
| Condenser water    | 50    | 110    |
| CO2 (ppm)          | 400   | 2000   |

---

**Next:** [Flat Line Sensor Tutorial]({{ "flat_line_sensor_tuntorial" | relative_url }})
