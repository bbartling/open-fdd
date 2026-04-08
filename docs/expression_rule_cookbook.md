---
title: Expression Rule Cookbook
parent: Fault rules for HVAC
nav_order: 2
---

# Expression Rule Cookbook

A quick guide for writing fault detection rules in **open-fdd**.

Rules use **YAML** with `type: expression`.
When the expression evaluates to **True**, the fault is flagged. open-fdd also makes **NumPy** available as `np`, so expressions can use functions like `np.abs()` or `np.maximum()`. 

---

## How inputs work

Rules define logical inputs, and open-fdd resolves them to real time-series columns under the hood.

Each input can now include labels from multiple ontologies, for example:

```yaml
inputs:
  Supply_Air_Temperature_Sensor:
    brick: Supply_Air_Temperature_Sensor
    haystack: discharge_air_temp_sensor
    dbo: SupplyAirTemperatureSensor
    s223: bldg1_supply_air_temperature_sensor
```

The rule expression still uses the **input key**:

```yaml
Supply_Air_Temperature_Sensor > max_temp
```

Not the Haystack, DBO, or 223P label. Those are only used for **resolution**.

**Runnable minimal example:** [`examples/column_map_resolver_workshop/simple_ontology_demo.py`](https://github.com/bbartling/open-fdd/blob/master/examples/column_map_resolver_workshop/simple_ontology_demo.py) (rule YAML uses the same `inputs` pattern; the script prints one run per ontology key in `column_map`).

---

## What this means

open-fdd lets one rule work across different naming systems:

* **Brick**
* **Haystack**
* **DBO**
* **ASHRAE 223P-style names**

You write the rule once.
The platform matches the best available ontology label to the real DataFrame column. 

---

## Why this is useful

This keeps rule logic clean while making the same rule easier to reuse across:

* Brick-first AFDD deployments
* Haystack-based projects
* DBO-style models
* future ontology adapters

The equation stays readable, and the ontology mapping stays inside `inputs`. 

---

## Basic rule structure

A rule usually has 3 parts:

### 1. Inputs

Logical point names plus ontology aliases.

### 2. Params

Thresholds and constants.

### 3. Expression

The fault logic.

Use:

* `&` for AND
* `|` for OR
* `~` for NOT

You can also use pandas-style logic like `.diff()`, `.rolling()`, and `.notna()`. 

---

## Minimal example

```yaml
name: high_temp_check
type: expression
flag: high_temp_flag

inputs:
  Supply_Air_Temperature_Sensor:
    brick: Supply_Air_Temperature_Sensor
    haystack: discharge_air_temp_sensor
    dbo: SupplyAirTemperatureSensor
    s223: bldg1_supply_air_temperature_sensor

params:
  max_temp: 90.0

expression: |
  Supply_Air_Temperature_Sensor > max_temp
```

---

## Schedule and weather gating (unoccupied operation)

Use this pattern when a fault should apply only during **expected unoccupied hours** (e.g. nights and weekends) and only when **outside air is in a normal analysis band** (so you **ignore** the rule during extreme cold or heat).

The engine injects two boolean **Series** aligned to each row (same length as your DataFrame):

| Name | Meaning |
|------|--------|
| `schedule_occupied` | **True** during configured weekly hours (default: all **True** if you omit `params.schedule`). |
| `weather_allows_fdd` | **True** when OAT is inside `[low, high]` for the chosen units (default: all **True** if you omit `params.weather_band`). |

**Time axis:** Rules need either a **`DatetimeIndex`** on the DataFrame or a **`timestamp`** column (or pass `timestamp_col` to `RuleRunner.run()`). Schedule uses **local** wall-clock `weekday` and `hour` on those timestamps (Monday = 0 … Sunday = 6).

**Typical fault** — equipment **running** (fan, compressor command, or status) when the site should be **unoccupied**, but only when OAT is between e.g. **32 °F and 85 °F**:

```text
(core_running) & ~schedule_occupied & weather_allows_fdd
```

- `core_running`: your usual command/status logic (fan speed, enable, etc.).
- `~schedule_occupied`: **not** in the weekly “office open” window (e.g. Mon–Fri 08:00–17:00).
- `weather_allows_fdd`: suppresses the fault when OAT is **below** the cold cutoff or **above** the heat cutoff (analysis ignored in extremes).

**Params:**

```yaml
params:
  # Fan / threshold (example)
  fan_on: 0.01

  schedule:
    weekdays: [0, 1, 2, 3, 4]   # Mon–Fri; omit or use enabled: false for 24/7 schedule mask (all True)
    start_hour: 8              # inclusive (local hour 0–23)
    end_hour: 17               # exclusive (last minute included is 16:59)
    # enabled: false           # optional: disable schedule injection (schedule_occupied all True)

  weather_band:
    oat_input: Outside_Air_Temperature_Sensor   # must match an entry under inputs
    low: 32
    high: 85
    units: imperial            # imperial = °F; metric = °C for low/high
    # enabled: false           # optional: disable OAT band (weather_allows_fdd all True)
```

**Metric example** (~0 °C … ~29 °C for the same idea as 32–85 °F):

```yaml
  weather_band:
    oat_input: Outside_Air_Temperature_Sensor
    low: 0.0
    high: 29.5
    units: metric
```

### Example — AHU / FCU / VRF / heat pump: operating outside office schedule

Map **fan** (or **status**) and **OAT** in `inputs`; tune `equipment_type` for your library.

```yaml
name: hvac_operating_outside_office_schedule
description: Supply fan (or unit) active when weekly schedule says unoccupied; suppressed outside OAT band
type: expression
flag: operating_unoccupied_schedule_flag
equipment_type: [AHU, VAV_AHU, Fan_Coil_Unit, HVAC, Heat_Pump]

inputs:
  Supply_Fan_Speed_Command:
    brick: Supply_Fan_Speed_Command
    haystack: supply_fan_speed_cmd
    dbo: SupplyFanSpeedCommand
    s223: bldg1_supply_fan_speed_command
  Outside_Air_Temperature_Sensor:
    brick: Outside_Air_Temperature_Sensor
    haystack: outside_air_temp_sensor
    dbo: OutsideAirTemperatureSensor
    s223: bldg1_outside_air_temperature_sensor

params:
  fan_on: 0.01
  schedule:
    weekdays: [0, 1, 2, 3, 4]
    start_hour: 8
    end_hour: 17
  weather_band:
    oat_input: Outside_Air_Temperature_Sensor
    low: 32
    high: 85
    units: imperial

expression: |
  (Supply_Fan_Speed_Command > fan_on) & ~schedule_occupied & weather_allows_fdd
```

For **binary fan status** (0/1), use `(Supply_Fan_Status > 0.5) & ~schedule_occupied & weather_allows_fdd` and map `Supply_Fan_Status` in `inputs`. VRF / packaged units often expose a **run** or **compressor** command — use the same gating pattern with your Brick/Haystack points.

---

## Recommended mental model

Think of it like this:

* **`inputs`** = logical sensor names plus ontology aliases
* **resolver** = finds the matching real column
* **expression** = the actual fault logic

So the YAML stays human-readable, while the ontology resolution happens behind the scenes. 

---

## AHU rules (reference-style)

The following rules follow common industry practice for air-handling fault detection. Rules A through M are adapted from ASHRAE Guideline 36 (GL36) AFDD guidance. Thresholds and logic are tunable; adjust params for your site. **Each `inputs` entry uses the same shape:** `brick`, `haystack`, `dbo`, and `s223` (see [ontology labels](#ontology-labels)).

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
    haystack: supply_air_static_pressure_sensor
    dbo: SupplyAirStaticPressureSensor
    s223: bldg1_supply_air_static_pressure_sensor
  Supply_Air_Static_Pressure_Setpoint:
    brick: Supply_Air_Static_Pressure_Setpoint
    haystack: supply_air_static_press_sp
    dbo: SupplyAirStaticPressureSetpoint
    s223: bldg1_supply_air_static_pressure_setpoint
  Supply_Fan_Speed_Command:
    brick: Supply_Fan_Speed_Command
    haystack: supply_fan_speed_cmd
    dbo: SupplyFanSpeedCommand
    s223: bldg1_supply_fan_speed_command

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
    haystack: mixed_air_temp_sensor
    dbo: MixedAirTemperatureSensor
    s223: bldg1_mixed_air_temperature_sensor
  Return_Air_Temperature_Sensor:
    brick: Return_Air_Temperature_Sensor
    haystack: return_air_temp_sensor
    dbo: ReturnAirTemperatureSensor
    s223: bldg1_return_air_temperature_sensor
  Outside_Air_Temperature_Sensor:
    brick: Outside_Air_Temperature_Sensor
    haystack: outside_air_temp_sensor
    dbo: OutsideAirTemperatureSensor
    s223: bldg1_outside_air_temperature_sensor
  Supply_Fan_Speed_Command:
    brick: Supply_Fan_Speed_Command
    haystack: supply_fan_speed_cmd
    dbo: SupplyFanSpeedCommand
    s223: bldg1_supply_fan_speed_command

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
    haystack: mixed_air_temp_sensor
    dbo: MixedAirTemperatureSensor
    s223: bldg1_mixed_air_temperature_sensor
  Return_Air_Temperature_Sensor:
    brick: Return_Air_Temperature_Sensor
    haystack: return_air_temp_sensor
    dbo: ReturnAirTemperatureSensor
    s223: bldg1_return_air_temperature_sensor
  Outside_Air_Temperature_Sensor:
    brick: Outside_Air_Temperature_Sensor
    haystack: outside_air_temp_sensor
    dbo: OutsideAirTemperatureSensor
    s223: bldg1_outside_air_temperature_sensor
  Supply_Fan_Speed_Command:
    brick: Supply_Fan_Speed_Command
    haystack: supply_fan_speed_cmd
    dbo: SupplyFanSpeedCommand
    s223: bldg1_supply_fan_speed_command

params:
  blend_tol: 1.15
  rat_tol: 1.15
  oat_tol: 1.15

expression: |
  (Mixed_Air_Temperature_Sensor - blend_tol > np.maximum(Return_Air_Temperature_Sensor + rat_tol, Outside_Air_Temperature_Sensor + oat_tol)) & (Supply_Fan_Speed_Command > 0.01)
```

*Hunting/oscillation — see [rule types (hunting)](rules/overview#rule-types).*

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
    haystack: mixed_air_temp_sensor
    dbo: MixedAirTemperatureSensor
    s223: bldg1_mixed_air_temperature_sensor
  Supply_Air_Temperature_Sensor:
    brick: Supply_Air_Temperature_Sensor
    haystack: discharge_air_temp_sensor
    dbo: SupplyAirTemperatureSensor
    s223: bldg1_supply_air_temperature_sensor
  Valve_Command:
    brick: Valve_Command
    haystack: valve_cmd
    dbo: ValveCommand
    s223: bldg1_valve_command
  Supply_Fan_Speed_Command:
    brick: Supply_Fan_Speed_Command
    haystack: supply_fan_speed_cmd
    dbo: SupplyFanSpeedCommand
    s223: bldg1_supply_fan_speed_command

params:
  blend_tol: 1.15
  sat_tol: 1.15
  fan_delta_t: 0.55

expression: |
  (Supply_Air_Temperature_Sensor + sat_tol <= Mixed_Air_Temperature_Sensor - blend_tol + fan_delta_t) & (Valve_Command > 0.01) & (Supply_Fan_Speed_Command > 0.01)
```

*OA fraction — see [rule types (oa_fraction)](rules/overview#rule-types).*

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
    haystack: discharge_air_temp_sensor
    dbo: SupplyAirTemperatureSensor
    s223: bldg1_supply_air_temperature_sensor
  Supply_Air_Temperature_Setpoint:
    brick: Supply_Air_Temperature_Setpoint
    haystack: supply_air_temp_sp
    dbo: SupplyAirTemperatureSetpoint
    s223: bldg1_supply_air_temperature_setpoint
  Valve_Command:
    brick: Valve_Command
    haystack: valve_cmd
    dbo: ValveCommand
    s223: bldg1_valve_command
  Supply_Fan_Speed_Command:
    brick: Supply_Fan_Speed_Command
    haystack: supply_fan_speed_cmd
    dbo: SupplyFanSpeedCommand
    s223: bldg1_supply_fan_speed_command

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
    haystack: mixed_air_temp_sensor
    dbo: MixedAirTemperatureSensor
    s223: bldg1_mixed_air_temperature_sensor
  Supply_Air_Temperature_Sensor:
    brick: Supply_Air_Temperature_Sensor
    haystack: discharge_air_temp_sensor
    dbo: SupplyAirTemperatureSensor
    s223: bldg1_supply_air_temperature_sensor
  Damper_Position_Command:
    brick: Damper_Position_Command
    haystack: damper_position_cmd
    dbo: DamperPositionCommand
    s223: bldg1_damper_position_command
  Valve_Command:
    brick: Valve_Command
    haystack: valve_cmd
    dbo: ValveCommand
    s223: bldg1_valve_command

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
    haystack: outside_air_temp_sensor
    dbo: OutsideAirTemperatureSensor
    s223: bldg1_outside_air_temperature_sensor
  Supply_Air_Temperature_Setpoint:
    brick: Supply_Air_Temperature_Setpoint
    haystack: supply_air_temp_sp
    dbo: SupplyAirTemperatureSetpoint
    s223: bldg1_supply_air_temperature_setpoint
  Damper_Position_Command:
    brick: Damper_Position_Command
    haystack: damper_position_cmd
    dbo: DamperPositionCommand
    s223: bldg1_damper_position_command
  Valve_Command:
    brick: Valve_Command
    haystack: valve_cmd
    dbo: ValveCommand
    s223: bldg1_valve_command

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
    haystack: outside_air_temp_sensor
    dbo: OutsideAirTemperatureSensor
    s223: bldg1_outside_air_temperature_sensor
  Mixed_Air_Temperature_Sensor:
    brick: Mixed_Air_Temperature_Sensor
    haystack: mixed_air_temp_sensor
    dbo: MixedAirTemperatureSensor
    s223: bldg1_mixed_air_temperature_sensor
  Valve_Command:
    brick: Valve_Command
    haystack: valve_cmd
    dbo: ValveCommand
    s223: bldg1_valve_command
  Damper_Position_Command:
    brick: Damper_Position_Command
    haystack: damper_position_cmd
    dbo: DamperPositionCommand
    s223: bldg1_damper_position_command

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
    haystack: outside_air_temp_sensor
    dbo: OutsideAirTemperatureSensor
    s223: bldg1_outside_air_temperature_sensor
  Mixed_Air_Temperature_Sensor:
    brick: Mixed_Air_Temperature_Sensor
    haystack: mixed_air_temp_sensor
    dbo: MixedAirTemperatureSensor
    s223: bldg1_mixed_air_temperature_sensor
  Damper_Position_Command:
    brick: Damper_Position_Command
    haystack: damper_position_cmd
    dbo: DamperPositionCommand
    s223: bldg1_damper_position_command

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
    haystack: discharge_air_temp_sensor
    dbo: SupplyAirTemperatureSensor
    s223: bldg1_supply_air_temperature_sensor
  Mixed_Air_Temperature_Sensor:
    brick: Mixed_Air_Temperature_Sensor
    haystack: mixed_air_temp_sensor
    dbo: MixedAirTemperatureSensor
    s223: bldg1_mixed_air_temperature_sensor
  Valve_Command:
    brick: Valve_Command
    haystack: valve_cmd
    dbo: ValveCommand
    s223: bldg1_valve_command
  Damper_Position_Command:
    brick: Damper_Position_Command
    haystack: damper_position_cmd
    dbo: DamperPositionCommand
    s223: bldg1_damper_position_command

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
    haystack: discharge_air_temp_sensor
    dbo: SupplyAirTemperatureSensor
    s223: bldg1_supply_air_temperature_sensor
  Supply_Air_Temperature_Setpoint:
    brick: Supply_Air_Temperature_Setpoint
    haystack: supply_air_temp_sp
    dbo: SupplyAirTemperatureSetpoint
    s223: bldg1_supply_air_temperature_setpoint
  Valve_Command:
    brick: Valve_Command
    haystack: valve_cmd
    dbo: ValveCommand
    s223: bldg1_valve_command
  Damper_Position_Command:
    brick: Damper_Position_Command
    haystack: damper_position_cmd
    dbo: DamperPositionCommand
    s223: bldg1_damper_position_command

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
    haystack: cooling_coil_entering_air_temp_sensor
    dbo: CoolingCoilEnteringAirTemperatureSensor
    s223: bldg1_cooling_coil_entering_air_temperature_sensor
  Cooling_Coil_Leaving_Air_Temperature_Sensor:
    brick: Cooling_Coil_Leaving_Air_Temperature_Sensor
    haystack: cooling_coil_leaving_air_temp_sensor
    dbo: CoolingCoilLeavingAirTemperatureSensor
    s223: bldg1_cooling_coil_leaving_air_temperature_sensor
  Heating_Valve_Command:
    brick: Valve_Command
    haystack: heating_valve_cmd
    dbo: HeatingValveCommand
    s223: bldg1_heating_valve_command
  Cooling_Valve_Command:
    brick: Valve_Command
    haystack: cooling_valve_cmd
    dbo: CoolingValveCommand
    s223: bldg1_cooling_valve_command
  Damper_Position_Command:
    brick: Damper_Position_Command
    haystack: damper_position_cmd
    dbo: DamperPositionCommand
    s223: bldg1_damper_position_command

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
    haystack: heating_coil_entering_air_temp_sensor
    dbo: HeatingCoilEnteringAirTemperatureSensor
    s223: bldg1_heating_coil_entering_air_temperature_sensor
  Heating_Coil_Leaving_Air_Temperature_Sensor:
    brick: Heating_Coil_Leaving_Air_Temperature_Sensor
    haystack: heating_coil_leaving_air_temp_sensor
    dbo: HeatingCoilLeavingAirTemperatureSensor
    s223: bldg1_heating_coil_leaving_air_temperature_sensor
  Heating_Valve_Command:
    brick: Valve_Command
    haystack: heating_valve_cmd
    dbo: HeatingValveCommand
    s223: bldg1_heating_valve_command
  Cooling_Valve_Command:
    brick: Valve_Command
    haystack: cooling_valve_cmd
    dbo: CoolingValveCommand
    s223: bldg1_cooling_valve_command
  Damper_Position_Command:
    brick: Damper_Position_Command
    haystack: damper_position_cmd
    dbo: DamperPositionCommand
    s223: bldg1_damper_position_command

params:
  enter_tol: 1.15
  leave_tol: 1.15
  fan_delta_t: 0.55
  econ_min_open: 0.12

expression: |
  ((Heating_Coil_Leaving_Air_Temperature_Sensor - Heating_Coil_Entering_Air_Temperature_Sensor) > np.sqrt(enter_tol**2 + leave_tol**2) + fan_delta_t) & (((Heating_Valve_Command == 0) & (Cooling_Valve_Command == 0) & (Damper_Position_Command > econ_min_open)) | ((Heating_Valve_Command == 0) & (Cooling_Valve_Command > 0) & (Damper_Position_Command > 0.9)) | ((Heating_Valve_Command == 0) & (Cooling_Valve_Command > 0) & (Damper_Position_Command <= econ_min_open)))
```

*Heat exchanger effectiveness — see [rule types (erv_efficiency)](rules/overview#rule-types).*


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
    haystack: differential_pressure_sensor
    dbo: DifferentialPressureSensor
    s223: bldg1_differential_pressure_sensor
  Differential_Pressure_Setpoint:
    brick: Differential_Pressure_Setpoint
    haystack: differential_pressure_sp
    dbo: DifferentialPressureSetpoint
    s223: bldg1_differential_pressure_setpoint
  Pump_Speed_Command:
    brick: Pump_Speed_Command
    haystack: pump_speed_cmd
    dbo: PumpSpeedCommand
    s223: bldg1_pump_speed_command

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
    haystack: water_flow_sensor
    dbo: WaterFlowSensor
    s223: bldg1_water_flow_sensor
  Pump_Speed_Command:
    brick: Pump_Speed_Command
    haystack: pump_speed_cmd
    dbo: PumpSpeedCommand
    s223: bldg1_pump_speed_command

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
    # Haystack native form is a tag set (e.g. chilled + water + supply + temp + sensor); slug below is for column_map.
    haystack: chilled_water_supply_temp_sensor
    dbo: ChilledWaterSupplyTemperatureSensor
    s223: bldg1_chilled_water_supply_temperature_sensor
  Chilled_Water_Supply_Temperature_Setpoint:
    brick: Chilled_Water_Supply_Temperature_Setpoint
    haystack: chilled_water_supply_temp_sp
    dbo: ChilledWaterSupplyTemperatureSetpoint
    s223: bldg1_chilled_water_supply_temperature_setpoint
  Pump_Speed_Command:
    brick: Pump_Speed_Command
    haystack: pump_speed_cmd
    dbo: PumpSpeedCommand
    s223: bldg1_pump_speed_command

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
    haystack: chiller_status
    dbo: ChillerStatus
    s223: bldg1_chiller_status

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

Flags when discharge air temperature is below a minimum (e.g. 80°F) while the supply fan is running. Indicates the heat pump is not heating effectively—possible issues with compressor, refrigerant, or reversing valve. Tunable via `min_discharge_temp`. Logic: if zone temp < 69°F (heating mode), the discharge should be warm; a cold discharge with the fan on and a cold zone indicates the heat pump is failing to heat.

```yaml
name: hp_discharge_cold_when_heating
description: Discharge air below minimum when fan on and zone is cold (heating mode)
type: expression
flag: hp_discharge_cold_flag
equipment_type: [Heat_Pump]

inputs:
  Supply_Air_Temperature_Sensor:
    brick: Supply_Air_Temperature_Sensor
    haystack: discharge_air_temp_sensor
    dbo: SupplyAirTemperatureSensor
    s223: bldg1_supply_air_temperature_sensor
  Zone_Temperature_Sensor:
    brick: Zone_Temperature_Sensor
    haystack: zone_air_temp_sensor
    dbo: ZoneTemperatureSensor
    s223: bldg1_zone_temperature_sensor
  Supply_Fan_Status:
    brick: Supply_Fan_Status
    haystack: supply_fan_status
    dbo: SupplyFanStatus
    s223: bldg1_supply_fan_status

params:
  min_discharge_temp: 85
  zone_cold_threshold: 69.0
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
    haystack: outside_air_temp_sensor
    dbo: OutsideAirTemperatureSensor
    s223: bldg1_outside_air_temperature_sensor
  Reheat_Valve_Command:
    brick: Valve_Command
    haystack: reheat_valve_cmd
    dbo: ReheatValveCommand
    s223: bldg1_reheat_valve_command

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
    haystack: damper_position_cmd
    dbo: DamperPositionCommand
    s223: bldg1_damper_position_command

params:
  full_open_pct: 97.5
  roll_samples: 105

expression: |
  (Damper_Position_Command > full_open_pct) & (Damper_Position_Command.rolling(roll_samples).min() > full_open_pct)
```

### Zone and IAQ bounds

For CO2 and zone temperature out-of-range checks, use the [bounds rule type](rules/overview#rule-types) — `co2_bounds` and `zone_temp_bounds` examples.

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
    haystack: outside_air_temp_sensor
    dbo: OutsideAirTemperatureSensor
    s223: bldg1_outside_air_temperature_sensor
  Damper_Position_Command:
    brick: Damper_Position_Command
    haystack: damper_position_cmd
    dbo: DamperPositionCommand
    s223: bldg1_damper_position_command

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
    haystack: outside_air_temp_sensor
    dbo: OutsideAirTemperatureSensor
    s223: bldg1_outside_air_temperature_sensor
  Damper_Position_Command:
    brick: Damper_Position_Command
    haystack: damper_position_cmd
    dbo: DamperPositionCommand
    s223: bldg1_damper_position_command
  Valve_Command:
    brick: Valve_Command
    haystack: valve_cmd
    dbo: ValveCommand
    s223: bldg1_valve_command

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
    haystack: mixed_air_temp_sensor
    dbo: MixedAirTemperatureSensor
    s223: bldg1_mixed_air_temperature_sensor
  Return_Air_Temperature_Sensor:
    brick: Return_Air_Temperature_Sensor
    haystack: return_air_temp_sensor
    dbo: ReturnAirTemperatureSensor
    s223: bldg1_return_air_temperature_sensor
  Outside_Air_Temperature_Sensor:
    brick: Outside_Air_Temperature_Sensor
    haystack: outside_air_temp_sensor
    dbo: OutsideAirTemperatureSensor
    s223: bldg1_outside_air_temperature_sensor
  Supply_Fan_Speed_Command:
    brick: Supply_Fan_Speed_Command
    haystack: supply_fan_speed_cmd
    dbo: SupplyFanSpeedCommand
    s223: bldg1_supply_fan_speed_command

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
    haystack: preheat_leaving_air_temp_sensor
    dbo: PreheatCoilLeavingAirTemperatureSensor
    s223: bldg1_preheat_coil_leaving_air_temperature_sensor
  Supply_Air_Temperature_Setpoint:
    brick: Supply_Air_Temperature_Setpoint
    haystack: supply_air_temp_sp
    dbo: SupplyAirTemperatureSetpoint
    s223: bldg1_supply_air_temperature_setpoint
  Outside_Air_Temperature_Sensor:
    brick: Outside_Air_Temperature_Sensor
    haystack: outside_air_temp_sensor
    dbo: OutsideAirTemperatureSensor
    s223: bldg1_outside_air_temperature_sensor
  Valve_Command:
    brick: Valve_Command
    haystack: valve_cmd
    dbo: ValveCommand
    s223: bldg1_valve_command

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

*weather_temp_stuck (flatline) — see [flatline rule type](rules/overview#rule-types).*

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
    haystack: outside_air_temp_sensor
    dbo: OutsideAirTemperatureSensor
    s223: bldg1_outside_air_temperature_sensor

params:
  spike_limit: 16.0

expression: |
  Outside_Air_Temperature_Sensor.diff().abs() > spike_limit
```

### RH bounds

For relative humidity out-of-range, use the [bounds rule type](rules/overview#rule-types) — `rh_bounds` example.

### Wind gust vs sustained

```yaml
name: weather_gust_lt_wind
description: Wind gust reported lower than sustained wind
type: expression
flag: fault_gust_lt_wind

inputs:
  Wind_Gust_Speed_Sensor:
    brick: Wind_Gust_Speed_Sensor
    haystack: wind_gust_speed_sensor
    dbo: WindGustSpeedSensor
    s223: bldg1_wind_gust_speed_sensor
  Wind_Speed_Sensor:
    brick: Wind_Speed_Sensor
    haystack: wind_speed_sensor
    dbo: WindSpeedSensor
    s223: bldg1_wind_speed_sensor

expression: |
  Wind_Gust_Speed_Sensor.notna() & Wind_Speed_Sensor.notna() & (Wind_Gust_Speed_Sensor < Wind_Speed_Sensor)
```

---

## Sensor validation (bounds & flatline)

Use the [bounds](rules/overview#rule-types) and [flatline](rules/overview#rule-types) rule types for generic sensor checks. Typical bounds:

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

## Follow-up (RFCs): nested selectors & cookbook matrix

**Flat ontology strings** (`brick`, `haystack`, `dbo`, `s223`, `223p` on each input) are implemented for **`column_map`** lookup in **`RuleRunner`**; see [ontology labels](#ontology-labels). **Nested** metadata (e.g. `selectors: { brick: { version: … } }`) or resolver plugins that read those structures are still **RFC** territory — GitHub **[#122](https://github.com/bbartling/open-fdd/issues/122)**. The **full AFDD stack** remains **Brick-first** for TTL-driven mapping.

**Cookbook matrix / generator:** When a selector schema is stable, add a **generated appendix** (logical input × Brick × Haystack × DBO × 223P) from a single CSV/YAML so the long cookbook does not drift. Until then, **`examples/column_map_resolver_workshop/simple_ontology_demo.py`** (with **`simple_ontology_rule.yaml`**) is the minimal reference for side-by-side **`column_map`** keys.

---

**Next:** [Fake fault schedule / flatline monitoring](https://bbartling.github.io/open-fdd-afdd-stack/howto/fake_fault_schedule_monitoring) (AFDD stack operators).
