---
title: DataFusion SQL cookbook
parent: Rule Cookbook
nav_order: 1
---

# DataFusion SQL FDD Cookbook

Open-FDD edge executes fault detection as **DataFusion SQL** against Apache Arrow historian tables. Copy-paste rules into the **SQL FDD Rules** tab or `POST /api/fdd-rules/{id}/test-sql`.

**Validated rule IDs** match the vibe19 pandas catalog (**59 rules**). Analyst mirror: [Pandas cookbook](pandas-cookbook.html).

---

## Table of contents

1. [Platform concepts](#platform-concepts)
2. [Fault confirmation delay (default 5 minutes)](#fault-confirmation-delay-default-5-minutes)
3. [Haystack → SQL columns](#haystack--sql-columns)
4. [Test & activate workflow](#test--activate-workflow)
5. [Sensor validation (sweep)](#sensor-validation-sweep)
6. [Control-loop hunting](#control-loop-hunting)
7. [Air handling units](#air-handling-units)
8. [VAV terminals](#vav-terminals)
9. [Central plant / condenser water](#central-plant--condenser-water)
10. [Heat pumps](#heat-pumps)
11. [Weather station](#weather-station)
12. [Trim & respond advisory](#trim--respond-advisory)
13. [Schedule & occupancy](#schedule--occupancy)
14. [Not yet in validated catalog](#not-yet-in-validated-catalog)
15. [Framework & parity docs](#framework--parity-docs)

---

## Platform concepts

| Term | Meaning |
|------|---------|
| `telemetry_pivot` | Wide historian table: `timestamp`, `equipment_id`, FDD input columns |
| `fault_raw` | Boolean — instantaneous fault condition (**required** output column) |
| `confirmation_seconds` | Minimum duration fault must hold before latching (API applies **after** SQL) |

Column names come from your **Haystack assignment graph**, not BACnet instance numbers.

### Rule template

```sql
-- confirmation_seconds: 300
SELECT
  timestamp,
  equipment_id,
  CASE
    WHEN oa_t IS NULL THEN false
    WHEN oa_t < -60.0 OR oa_t > 130.0 THEN true
    ELSE false
  END AS fault_raw
FROM telemetry_pivot
WHERE equipment_id = 'equip:your-id'
```

{: .important }
Always handle **`NULL`** — missing samples must not latch faults.

### Command scaling (0–1 vs 0–100 %)

```sql
CASE WHEN fan_cmd > 1.0 THEN fan_cmd / 100.0 ELSE fan_cmd END AS fan_norm
```

---

## Fault confirmation delay (default 5 minutes)

Raw rules can flicker true for one poll cycle. Open-FDD debounces **after** SQL returns `fault_raw`.

**Default:** `confirmation_seconds: 300` (5 minutes). Change per rule in the workbench or API.

```bash
curl -s -X POST http://127.0.0.1:8080/api/fdd-rules/RULE_ID/test-sql \
  -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"sql":"SELECT timestamp, equipment_id, ... AS fault_raw FROM telemetry_pivot","confirmation_seconds":300}'
```

---

## Haystack → SQL columns

Binding chain:

```
Driver point → Haystack point → FDD input → telemetry_pivot column
```

Validated catalog roles use Haystack-style names (`outside-air-temp`, `discharge-air-temp`, …). Map them to your pivot column names in assignments.

---

## Test & activate workflow

1. Paste SQL into **SQL FDD Rules** (or `test-sql` API)
2. Confirm `fault_raw` boolean column
3. Set `confirmation_seconds` (default 300)
4. Integrator JWT required to **activate**

---
## Sensor validation (sweep)

Sensor-sweep rules apply to **every modeled sensor** present on the equipment (not a single fixed point).

### SV-RANGE — Sensor out of hard range
**Family:** `sensor` · **Equipment:** `ahu`, `vav`, `chiller`, `boiler`, `weather`, `zone`, `heatpump`  
**Equation:** Any modeled sensor reads outside its physical hard range (e.g. OAT −60–130°F, SAT 30–150°F, CHWS 30–80°F).  
**Default confirmation:** 300 s

| Param | Label | Unit | Default | Range |
|-------|-------|------|--------:|-------|
| `range_scale_temperature` | Temp range scale | x | 1.0 | 0.5–2.0 |
| `range_scale_humidity` | Humidity range scale | x | 1.0 | 0.5–2.0 |
| `range_scale_pressure` | Pressure range scale | x | 1.0 | 0.5–2.0 |

```sql
-- confirmation_seconds: 300
-- Example hard-range screen for outdoor-air temperature (extend per sensor type)
SELECT
  timestamp, equipment_id, oa_t,
  CASE
    WHEN oa_t IS NULL THEN false
    WHEN oa_t < -60.0 OR oa_t > 130.0 THEN true
    ELSE false
  END AS fault_raw
FROM telemetry_pivot
```

### SV-FLATLINE — Sensor flatline (stuck)
**Family:** `sensor` · **Equipment:** `ahu`, `vav`, `chiller`, `boiler`, `weather`, `zone`, `heatpump`  
**Equation:** Sensor value unchanged (Δ ≤ tolerance) across the flatline window — stuck / frozen sensor.  
**Default confirmation:** 300 s

| Param | Label | Unit | Default | Range |
|-------|-------|------|--------:|-------|
| `flatline_tol` | Flatline tolerance | °F | 0.1 | 0.02–1.0 |
| `flatline_hours` | Flatline window | h | 1.0 | 0.5–8.0 |


{: .important }
**Simplified SQL variant.** Full rolling / multi-sensor logic for `SV-FLATLINE` is validated in Pandas. Use SQL for screening; use Pandas for parity and RCx studies.
```sql
-- confirmation_seconds: 300
-- rule: SV-FLATLINE — Sensor flatline (stuck)
-- equation: Sensor value unchanged (Δ ≤ tolerance) across the flatline window — stuck / frozen sensor.

SELECT
  timestamp,
  equipment_id,
  CASE
    -- Implement SV-FLATLINE against assigned Haystack → FDD columns
    -- NULL samples must not latch faults
    WHEN false THEN false  -- stub: never latch until equation is coded
    ELSE false
  END AS fault_raw
FROM telemetry_pivot
WHERE equipment_id = 'equip:your-id'
```

### SV-SPIKE — Sensor rate-of-change spike
**Family:** `sensor` · **Equipment:** `ahu`, `vav`, `chiller`, `boiler`, `weather`, `zone`, `heatpump`  
**Equation:** Sample-to-sample jump exceeds the physical spike limit for the sensor type.  
**Default confirmation:** 300 s

| Param | Label | Unit | Default | Range |
|-------|-------|------|--------:|-------|
| `spike_scale` | Spike limit scale (global) | x | 1.0 | 0.25–3.0 |
| `spike_scale_temperature` | Temp spike scale | x | 1.0 | 0.25–3.0 |
| `spike_scale_humidity` | Humidity spike scale | x | 1.0 | 0.25–3.0 |
| `spike_scale_pressure` | Pressure spike scale | x | 1.0 | 0.25–3.0 |


{: .important }
**Simplified SQL variant.** Full rolling / multi-sensor logic for `SV-SPIKE` is validated in Pandas. Use SQL for screening; use Pandas for parity and RCx studies.
```sql
-- confirmation_seconds: 300
-- rule: SV-SPIKE — Sensor rate-of-change spike
-- equation: Sample-to-sample jump exceeds the physical spike limit for the sensor type.

SELECT
  timestamp,
  equipment_id,
  CASE
    -- Implement SV-SPIKE against assigned Haystack → FDD columns
    -- NULL samples must not latch faults
    WHEN false THEN false  -- stub: never latch until equation is coded
    ELSE false
  END AS fault_raw
FROM telemetry_pivot
WHERE equipment_id = 'equip:your-id'
```

### SV-STALE — Stale data (no fresh samples)
**Family:** `sensor` · **Equipment:** `ahu`, `vav`, `chiller`, `boiler`, `weather`, `zone`, `heatpump`  
**Equation:** All modeled sensors unchanged over the stale window — data feed likely dropped.  
**Default confirmation:** 300 s

| Param | Label | Unit | Default | Range |
|-------|-------|------|--------:|-------|
| `stale_hours` | Stale window | h | 2.0 | 0.5–12.0 |

```sql
-- confirmation_seconds: 300
-- Stale feed: no fresh samples in window (edge confirmation / historian gap)
SELECT
  timestamp, equipment_id,
  CASE
    WHEN timestamp < (SELECT max(timestamp) FROM telemetry_pivot) - INTERVAL '2 hours' THEN true
    ELSE false
  END AS fault_raw
FROM telemetry_pivot
```

### SV-RATE — Context-aware sensor rate of change
**Family:** `sensor` · **Equipment:** `ahu`, `vav`, `chiller`, `boiler`, `weather`, `zone`, `heatpump`  
**Equation:** Implausible sustained rate-of-change for mapped sensors. Thresholds depend on quantity, location, and operating state (steady vs startup/shutdown transient). Engineering screening defaults — tune per site. Alias: SV-SLEW. Distinct from SV-SPIKE (one-sample jump), SV-RANGE, SV-FLATLINE, and PID-HUNT-1.  
**Default confirmation:** 600 s

| Param | Label | Unit | Default | Range |
|-------|-------|------|--------:|-------|
| `persistence_min` | Fault persistence | min | 10.0 | 5.0–60.0 |
| `transition_window_min` | Transition window | min | 20.0 | 5.0–60.0 |
| `max_gap_hours` | Max sample gap | h | 2.0 | 0.25–6.0 |
| `design_flow` | Design flow (flow profiles) | cfm | 0.0 | 0.0–100000.0 |
| `sensor_span` | Sensor span (flow/pressure) | eng | 0.0 | 0.0–100000.0 |


{: .important }
**Simplified SQL variant.** Full rolling / multi-sensor logic for `SV-RATE` is validated in Pandas. Use SQL for screening; use Pandas for parity and RCx studies.
```sql
-- confirmation_seconds: 600
-- rule: SV-RATE — Context-aware sensor rate of change
-- equation: Implausible sustained rate-of-change for mapped sensors. Thresholds depend on quantity, location, and operating state (steady vs startup/shutdown transient). Engineering screening defaults — tune per site. Alias: SV-SLEW. Distinct from SV-SPIKE (one-sample jump), SV-RANGE, SV-FLATLINE, and PID-HUNT-1.

SELECT
  timestamp,
  equipment_id,
  CASE
    -- Implement SV-RATE against assigned Haystack → FDD columns
    -- NULL samples must not latch faults
    WHEN false THEN false  -- stub: never latch until equation is coded
    ELSE false
  END AS fault_raw
FROM telemetry_pivot
WHERE equipment_id = 'equip:your-id'
```

## Control-loop hunting

### PID-HUNT-1 — Suspected control-output hunting
**Family:** `control` · **Equipment:** `ahu`, `vav`, `chiller`, `boiler`, `heatpump`  
**Equation:** Rolling 1h total variation of any 0–100% control output (dampers, valves, fan speeds, heat/cool cmds) with span ≥20%, TV ≥500 %·pts, ≥2.5 equivalent cycles, ≥4 reversals — suspected loop hunting (not proof of bad PID alone).  
**Default confirmation:** 0 s (rolling 1h window is its own persistence)

| Param | Label | Unit | Default | Range |
|-------|-------|------|--------:|-------|
| `change_deadband_pct` | Ignore changes below | % out | 1.0 | 0.0–10.0 |
| `minimum_span_pct` | Minimum observed span | % out | 20.0 | 5.0–100.0 |
| `total_variation_fault_pct` | Total travel threshold | %/h | 500.0 | 50.0–2000.0 |
| `minimum_equivalent_cycles` | Min equivalent cycles | cyc/h | 2.5 | 0.5–20.0 |
| `minimum_reversals` | Min direction reversals | count | 4 | 1–40 |
| `minimum_coverage_pct` | Minimum data coverage | % | 80.0 | 25.0–100.0 |


{: .important }
**Simplified SQL variant.** Full rolling / multi-sensor logic for `PID-HUNT-1` is validated in Pandas. Use SQL for screening; use Pandas for parity and RCx studies.
```sql
-- confirmation_seconds: 0  (rolling 1h window is its own persistence)
-- rule: PID-HUNT-1 — Suspected control-output hunting
-- equation: Rolling 1h total variation of any 0–100% control output (dampers, valves, fan speeds, heat/cool cmds) with span ≥20%, TV ≥500 %·pts, ≥2.5 equivalent cycles, ≥4 reversals — suspected loop hunting (not proof of bad PID alone).

SELECT
  timestamp,
  equipment_id,
  CASE
    -- Implement PID-HUNT-1 against assigned Haystack → FDD columns
    -- NULL samples must not latch faults
    WHEN false THEN false  -- stub: never latch until equation is coded
    ELSE false
  END AS fault_raw
FROM telemetry_pivot
WHERE equipment_id = 'equip:your-id'
```

## Air handling units

Includes GL36 FC1–FC15, AHU auxiliaries, economizer/ventilation, leakage, and outdoor-air screens.

### FC1 — Duct static below SP at full fan (GL36 A)
**Family:** `ahu` · **Equipment:** `ahu`  
**Equation:** DSP < DSPSP − εDSP AND VFDSPD ≥ 100% − εVFDSPD.  
**Default confirmation:** 300 s

| Param | Label | Unit | Default | Range |
|-------|-------|------|--------:|-------|
| `eps_dsp` | Duct-static error εDSP (GL36 default 0.1 in.w.c.) | in. w.c. | 0.12 | 0.0–0.5 |
| `eps_vfd_spd` | VFD speed error εVFDSPD (GL36 default 5%) | frac | 0.13 | 0.0–0.5 |
| `duct_static_err` | Legacy duct-static error (sets εDSP) | in. w.c. | 0.12 | 0.0–0.5 |
| `fan_hi` | Legacy fan-high threshold (sets εVFDSPD) | frac | 0.87 | 0.5–1.0 |
| `mode_delay_min` | Mode-change suspension (GL36 default 30) | min | 0.0 | 0.0–60.0 |

```sql
-- confirmation_seconds: 300
-- param: eps_dsp = 0.12 ; eps_vfd_spd = 0.13  (fan high = 1.0 − eps_vfd_spd = 0.87)
SELECT
  timestamp, equipment_id, duct_static, duct_static_sp, fan_cmd,
  CASE
    WHEN duct_static IS NULL OR duct_static_sp IS NULL OR fan_cmd IS NULL THEN false
    WHEN (CASE WHEN fan_cmd > 1.0 THEN fan_cmd / 100.0 ELSE fan_cmd END) >= 0.87
     AND duct_static < duct_static_sp - 0.12 THEN true
    ELSE false
  END AS fault_raw
FROM telemetry_pivot
WHERE equipment_id = 'equip:your-ahu'
```

### FC2 — MAT below OAT/RAT envelope (GL36 B)
**Family:** `ahu` · **Equipment:** `ahu`  
**Equation:** MATavg + εMAT < min(RATavg − εRAT, OATavg − εOAT).  
**Default confirmation:** 600 s

| Param | Label | Unit | Default | Range |
|-------|-------|------|--------:|-------|
| `eps_mat` | MAT sensor error εMAT (GL36 default 5°F) | °F | 1.15 | 0.0–10.0 |
| `eps_rat` | RAT sensor error εRAT (GL36 default 2°F) | °F | 1.15 | 0.0–10.0 |
| `eps_oat` | OAT sensor error εOAT (GL36 default 2°F local / 5°F global) | °F | 1.15 | 0.0–10.0 |
| `mix_tol` | Legacy master sensor tolerance (sets all ε values) | °F | 1.15 | 0.0–10.0 |
| `fan_on_min` | Fan-on command threshold | frac | 0.01 | 0.0–0.25 |
| `mode_delay_min` | Mode-change suspension (GL36 default 30) | min | 0.0 | 0.0–60.0 |

```sql
-- confirmation_seconds: 600
-- param: mix_tol = 1.15  (envelope = 2 * mix_tol = 2.3)
SELECT
  timestamp, equipment_id, mat, oa_t, rat, fan_cmd,
  CASE
    WHEN mat IS NULL OR oa_t IS NULL OR rat IS NULL OR fan_cmd IS NULL THEN false
    WHEN (CASE WHEN fan_cmd > 1.0 THEN fan_cmd / 100.0 ELSE fan_cmd END) >= 0.05
     AND mat < LEAST(oa_t, rat) - 2.3 THEN true
    ELSE false
  END AS fault_raw
FROM telemetry_pivot
WHERE equipment_id = 'equip:your-ahu'
```


### FC3 — MAT above OAT/RAT envelope (GL36 C)
**Family:** `ahu` · **Equipment:** `ahu`  
**Equation:** MATavg − εMAT > max(RATavg + εRAT, OATavg + εOAT).  
**Default confirmation:** 600 s

| Param | Label | Unit | Default | Range |
|-------|-------|------|--------:|-------|
| `eps_mat` | MAT sensor error εMAT (GL36 default 5°F) | °F | 1.15 | 0.0–10.0 |
| `eps_rat` | RAT sensor error εRAT (GL36 default 2°F) | °F | 1.15 | 0.0–10.0 |
| `eps_oat` | OAT sensor error εOAT (GL36 default 2°F local / 5°F global) | °F | 1.15 | 0.0–10.0 |
| `mix_tol` | Legacy master sensor tolerance (sets all ε values) | °F | 1.15 | 0.0–10.0 |
| `fan_on_min` | Fan-on command threshold | frac | 0.01 | 0.0–0.25 |
| `mode_delay_min` | Mode-change suspension (GL36 default 30) | min | 0.0 | 0.0–60.0 |

```sql
-- confirmation_seconds: 600
SELECT
  timestamp, equipment_id, mat, oa_t, rat, fan_cmd,
  CASE
    WHEN mat IS NULL OR oa_t IS NULL OR rat IS NULL OR fan_cmd IS NULL THEN false
    WHEN (CASE WHEN fan_cmd > 1.0 THEN fan_cmd / 100.0 ELSE fan_cmd END) >= 0.05
     AND mat > GREATEST(oa_t, rat) + 2.3 THEN true
    ELSE false
  END AS fault_raw
FROM telemetry_pivot
WHERE equipment_id = 'equip:your-ahu'
```


### FC4 — PID hunting (operating-state oscillation)
**Family:** `ahu` · **Equipment:** `ahu`  
**Equation:** ΔOS > ΔOSmax during the prior 60-minute moving window.  
**Default confirmation:** 3600 s

| Param | Label | Unit | Default | Range |
|-------|-------|------|--------:|-------|
| `delta_os_max` | Max mode changes/hr ΔOSmax (GL36 default 7) | count | 5 | 1–30 |
| `mode_delay_min` | Mode-change suspension (GL36 default 30) | min | 0.0 | 0.0–60.0 |


{: .important }
**Simplified SQL variant.** Full rolling / multi-sensor logic for `FC4` is validated in Pandas. Use SQL for screening; use Pandas for parity and RCx studies.
```sql
-- confirmation_seconds: 3600
-- rule: FC4 — PID hunting (operating-state oscillation)
-- equation: More than 5 operating-mode entry transitions in any hour (heating/econ/mech modes).

SELECT
  timestamp,
  equipment_id,
  outside_air_damper,
  cooling_valve,
  fan_cmd,
  CASE
    -- Implement FC4 against assigned Haystack → FDD columns
    -- NULL samples must not latch faults
    WHEN false THEN false  -- stub: never latch until equation is coded
    ELSE false
  END AS fault_raw
FROM telemetry_pivot
WHERE equipment_id = 'equip:your-id'
```

### FC5 — SAT cold when heating commanded (GL36 D)
**Family:** `ahu` · **Equipment:** `ahu`  
**Equation:** SATavg + εSAT ≤ MATavg − εMAT + ΔTSF while heating is commanded.  
**Default confirmation:** 600 s

| Param | Label | Unit | Default | Range |
|-------|-------|------|--------:|-------|
| `eps_sat` | SAT sensor error εSAT (GL36 default 2°F) | °F | 1.15 | 0.0–10.0 |
| `eps_mat` | MAT sensor error εMAT (GL36 default 5°F) | °F | 1.15 | 0.0–10.0 |
| `delta_supply_fan` | Supply-fan heat rise ΔTSF (GL36 default 2°F) | °F | 0.55 | 0.0–5.0 |
| `htg_on_min` | Heating-command ON threshold | frac | 0.01 | 0.0–0.25 |
| `mix_tol` | Legacy master sensor tolerance (sets all ε values) | °F | 1.15 | 0.0–10.0 |
| `fan_on_min` | Fan-on command threshold | frac | 0.01 | 0.0–0.25 |
| `mode_delay_min` | Mode-change suspension (GL36 default 30) | min | 0.0 | 0.0–60.0 |

```sql
-- confirmation_seconds: 600
-- param: mix_tol = 1.15 ; delta_supply_fan = 0.55
SELECT
  timestamp, equipment_id, sat, mat, htg_valve_pct, fan_cmd,
  CASE
    WHEN sat IS NULL OR mat IS NULL OR htg_valve_pct IS NULL OR fan_cmd IS NULL THEN false
    WHEN (CASE WHEN fan_cmd > 1.0 THEN fan_cmd / 100.0 ELSE fan_cmd END) >= 0.05
     AND (CASE WHEN htg_valve_pct > 1.0 THEN htg_valve_pct / 100.0 ELSE htg_valve_pct END) > 0.01
     AND (sat + 1.15) <= (mat - 1.15 + 0.55) THEN true
    ELSE false
  END AS fault_raw
FROM telemetry_pivot
WHERE equipment_id = 'equip:your-ahu'
```


### FC6 — Estimated OA fraction mismatch
**Family:** `ahu` · **Equipment:** `ahu`  
**Equation:** |RATavg−OATavg| ≥ ΔTmin AND |estimated OA% − design min OA%| > εF.  
**Default confirmation:** 600 s

| Param | Label | Unit | Default | Range |
|-------|-------|------|--------:|-------|
| `eps_airflow` | Airflow error εF (GL36 default 30%) | frac | 0.15 | 0.05–1.0 |
| `delta_t_min` | Minimum \|OAT−RAT\| ΔTmin (GL36 default 10°F) | °F | 5.0 | 0.0–30.0 |
| `airflow_err` | Legacy OA-fraction error (sets εF) | frac | 0.15 | 0.05–1.0 |
| `oat_rat_delta_min` | Legacy OAT/RAT guard (sets ΔTmin) | °F | 5.0 | 0.0–30.0 |
| `min_cfm_design` | Design min OA CFM | cfm | 5000 | 500–20000 |
| `fan_on_min` | Fan-on command threshold | frac | 0.01 | 0.0–0.25 |
| `mode_delay_min` | Mode-change suspension (GL36 default 30) | min | 0.0 | 0.0–60.0 |

```sql
-- confirmation_seconds: 600
-- rule: FC6 — Estimated OA fraction mismatch
-- equation: |RAT−OAT| ≥ 5°F AND |estimated OA% − design min OA%| > 15% in heating/mech-only modes.

SELECT
  timestamp,
  equipment_id,
  mixed_air_temp,
  outside_air_temp,
  return_air_temp,
  vav_total_airflow,
  CASE
    -- Implement FC6 against assigned Haystack → FDD columns
    -- NULL samples must not latch faults
    WHEN false THEN false  -- stub: never latch until equation is coded
    ELSE false
  END AS fault_raw
FROM telemetry_pivot
WHERE equipment_id = 'equip:your-id'
```

### FC7 — SAT low with full heating (GL36 E)
**Family:** `ahu` · **Equipment:** `ahu`  
**Equation:** SATavg < SATSP − εSAT AND HC ≥ full-heating threshold.  
**Default confirmation:** 600 s

| Param | Label | Unit | Default | Range |
|-------|-------|------|--------:|-------|
| `eps_sat` | SAT sensor error εSAT (GL36 default 2°F) | °F | 1.0 | 0.0–10.0 |
| `sat_err` | Legacy SAT error (sets εSAT) | °F | 1.0 | 0.0–10.0 |
| `htg_full_min` | Full-heating threshold (GL36 99%) | frac | 0.9 | 0.5–1.0 |
| `fan_on_min` | Fan-on command threshold | frac | 0.01 | 0.0–0.25 |
| `mode_delay_min` | Mode-change suspension (GL36 default 30) | min | 0.0 | 0.0–60.0 |

```sql
-- confirmation_seconds: 600
-- rule: FC7 — SAT low with full heating (GL36 E)
-- equation: Fan on AND heating > 90% AND SAT < SAT SP − 1.0°F.

SELECT
  timestamp,
  equipment_id,
  discharge_air_temp,
  discharge_air_temp_sp,
  fan_cmd,
  heating_valve,
  CASE
    -- Implement FC7 against assigned Haystack → FDD columns
    -- NULL samples must not latch faults
    WHEN false THEN false  -- stub: never latch until equation is coded
    ELSE false
  END AS fault_raw
FROM telemetry_pivot
WHERE equipment_id = 'equip:your-id'
```

### FC8 — SAT/MAT mismatch in economizer (GL36 F)
**Family:** `ahu` · **Equipment:** `ahu`  
**Equation:** |SATavg − ΔTSF − MATavg| > √(εSAT² + εMAT²) in OS#2.  
**Default confirmation:** 600 s

| Param | Label | Unit | Default | Range |
|-------|-------|------|--------:|-------|
| `eps_sat` | SAT sensor error εSAT (GL36 default 2°F) | °F | 1.15 | 0.0–10.0 |
| `eps_mat` | MAT sensor error εMAT (GL36 default 5°F) | °F | 1.15 | 0.0–10.0 |
| `delta_supply_fan` | Supply-fan heat rise ΔTSF (GL36 default 2°F) | °F | 0.55 | 0.0–5.0 |
| `econ_min_pos` | Economizer minimum-position threshold | frac | 0.05 | 0.0–0.5 |
| `clg_inactive_max` | Cooling-command inactive ceiling | frac | 0.1 | 0.0–0.5 |
| `mix_tol` | Legacy master sensor tolerance (sets all ε values) | °F | 1.15 | 0.0–10.0 |
| `supply_tol` | Legacy SAT tolerance master (sets εSAT) | °F | 1.15 | 0.0–10.0 |
| `mode_delay_min` | Mode-change suspension (GL36 default 30) | min | 0.0 | 0.0–60.0 |

```sql
-- confirmation_seconds: 600
-- rule: FC8 — SAT/MAT mismatch in economizer (GL36 F)
-- equation: Economizer open, CHW < 10%, |SAT − 0.55°F − MAT| > √(supply_tol²+mix_tol²).

SELECT
  timestamp,
  equipment_id,
  discharge_air_temp,
  mixed_air_temp,
  outside_air_damper,
  cooling_valve,
  CASE
    -- Implement FC8 against assigned Haystack → FDD columns
    -- NULL samples must not latch faults
    WHEN false THEN false  -- stub: never latch until equation is coded
    ELSE false
  END AS fault_raw
FROM telemetry_pivot
WHERE equipment_id = 'equip:your-id'
```

### FC9 — OAT too warm for free cooling (GL36 G)
**Family:** `ahu` · **Equipment:** `ahu`  
**Equation:** OATavg − εOAT > SATSP − ΔTSF + εSAT in OS#2.  
**Default confirmation:** 600 s

| Param | Label | Unit | Default | Range |
|-------|-------|------|--------:|-------|
| `eps_oat` | OAT sensor error εOAT (GL36 default 2°F local / 5°F global) | °F | 1.15 | 0.0–10.0 |
| `eps_sat` | SAT sensor error εSAT (GL36 default 2°F) | °F | 1.15 | 0.0–10.0 |
| `delta_supply_fan` | Supply-fan heat rise ΔTSF (GL36 default 2°F) | °F | 0.55 | 0.0–5.0 |
| `econ_min_pos` | Economizer minimum-position threshold | frac | 0.05 | 0.0–0.5 |
| `clg_inactive_max` | Cooling-command inactive ceiling | frac | 0.1 | 0.0–0.5 |
| `mix_tol` | Legacy master sensor tolerance (sets all ε values) | °F | 1.15 | 0.0–10.0 |
| `mode_delay_min` | Mode-change suspension (GL36 default 30) | min | 0.0 | 0.0–60.0 |

```sql
-- confirmation_seconds: 600
-- rule: FC9 — OAT too warm for free cooling (GL36 G)
-- equation: Economizer open, CHW < 10%, OAT − mix_tol > SAT SP − 0.55°F + mix_tol.

SELECT
  timestamp,
  equipment_id,
  outside_air_temp,
  discharge_air_temp_sp,
  outside_air_damper,
  cooling_valve,
  CASE
    -- Implement FC9 against assigned Haystack → FDD columns
    -- NULL samples must not latch faults
    WHEN false THEN false  -- stub: never latch until equation is coded
    ELSE false
  END AS fault_raw
FROM telemetry_pivot
WHERE equipment_id = 'equip:your-id'
```

### FC10 — OAT/MAT mismatch + mech cooling (GL36 H)
**Family:** `ahu` · **Equipment:** `ahu`  
**Equation:** |MATavg − OATavg| > √(εMAT² + εOAT²) in OS#3.  
**Default confirmation:** 600 s

| Param | Label | Unit | Default | Range |
|-------|-------|------|--------:|-------|
| `eps_mat` | MAT sensor error εMAT (GL36 default 5°F) | °F | 1.15 | 0.0–10.0 |
| `eps_oat` | OAT sensor error εOAT (GL36 default 2°F local / 5°F global) | °F | 1.15 | 0.0–10.0 |
| `econ_full_open` | Economizer full-open threshold | frac | 0.9 | 0.5–1.0 |
| `clg_on_min` | Cooling-command ON threshold | frac | 0.01 | 0.0–0.25 |
| `mix_tol` | Legacy master sensor tolerance (sets all ε values) | °F | 1.15 | 0.0–10.0 |
| `mode_delay_min` | Mode-change suspension (GL36 default 30) | min | 0.0 | 0.0–60.0 |

```sql
-- confirmation_seconds: 600
-- rule: FC10 — OAT/MAT mismatch + mech cooling (GL36 H)
-- equation: CHW > 1%, economizer > 90%, |MAT − OAT| > √(mix_tol²+mix_tol²).

SELECT
  timestamp,
  equipment_id,
  mixed_air_temp,
  outside_air_temp,
  outside_air_damper,
  cooling_valve,
  CASE
    -- Implement FC10 against assigned Haystack → FDD columns
    -- NULL samples must not latch faults
    WHEN false THEN false  -- stub: never latch until equation is coded
    ELSE false
  END AS fault_raw
FROM telemetry_pivot
WHERE equipment_id = 'equip:your-id'
```

### FC11 — OAT/MAT mismatch economizer-only (GL36 I)
**Family:** `ahu` · **Equipment:** `ahu`  
**Equation:** OATavg + εOAT < SATSP − ΔTSF − εSAT in OS#3.  
**Default confirmation:** 600 s

| Param | Label | Unit | Default | Range |
|-------|-------|------|--------:|-------|
| `eps_oat` | OAT sensor error εOAT (GL36 default 2°F local / 5°F global) | °F | 1.15 | 0.0–10.0 |
| `eps_sat` | SAT sensor error εSAT (GL36 default 2°F) | °F | 1.15 | 0.0–10.0 |
| `delta_supply_fan` | Supply-fan heat rise ΔTSF (GL36 default 2°F) | °F | 0.55 | 0.0–5.0 |
| `econ_full_open` | Economizer full-open threshold | frac | 0.9 | 0.5–1.0 |
| `clg_on_min` | Cooling-command ON threshold | frac | 0.01 | 0.0–0.25 |
| `mix_tol` | Legacy master sensor tolerance (sets all ε values) | °F | 1.15 | 0.0–10.0 |
| `mode_delay_min` | Mode-change suspension (GL36 default 30) | min | 0.0 | 0.0–60.0 |

```sql
-- confirmation_seconds: 600
-- rule: FC11 — OAT/MAT mismatch economizer-only (GL36 I)
-- equation: CHW > 1%, economizer > 90%, OAT + mix_tol < SAT SP − 0.55°F − mix_tol.

SELECT
  timestamp,
  equipment_id,
  outside_air_temp,
  discharge_air_temp_sp,
  outside_air_damper,
  cooling_valve,
  CASE
    -- Implement FC11 against assigned Haystack → FDD columns
    -- NULL samples must not latch faults
    WHEN false THEN false  -- stub: never latch until equation is coded
    ELSE false
  END AS fault_raw
FROM telemetry_pivot
WHERE equipment_id = 'equip:your-id'
```

### FC12 — SAT above blend in cooling (GL36 J)
**Family:** `ahu` · **Equipment:** `ahu`  
**Equation:** SATavg − εSAT − ΔTSF ≥ MATavg + εMAT in OS#3/OS#4.  
**Default confirmation:** 600 s

| Param | Label | Unit | Default | Range |
|-------|-------|------|--------:|-------|
| `eps_sat` | SAT sensor error εSAT (GL36 default 2°F) | °F | 1.15 | 0.0–10.0 |
| `eps_mat` | MAT sensor error εMAT (GL36 default 5°F) | °F | 1.15 | 0.0–10.0 |
| `delta_supply_fan` | Supply-fan heat rise ΔTSF (GL36 default 2°F) | °F | 0.55 | 0.0–5.0 |
| `econ_min_pos` | Economizer minimum-position threshold | frac | 0.05 | 0.0–0.5 |
| `econ_full_open` | Economizer full-open threshold | frac | 0.9 | 0.5–1.0 |
| `clg_on_min` | Cooling-command ON threshold | frac | 0.01 | 0.0–0.25 |
| `mix_tol` | Legacy master sensor tolerance (sets all ε values) | °F | 1.15 | 0.0–10.0 |
| `supply_tol` | Legacy SAT tolerance master (sets εSAT) | °F | 1.15 | 0.0–10.0 |
| `mode_delay_min` | Mode-change suspension (GL36 default 30) | min | 0.0 | 0.0–60.0 |

```sql
-- confirmation_seconds: 600
-- rule: FC12 — SAT above blend in cooling (GL36 J)
-- equation: CHW > 1%, SAT − supply_tol − 0.55°F > MAT + mix_tol at min or full economizer.

SELECT
  timestamp,
  equipment_id,
  discharge_air_temp,
  mixed_air_temp,
  outside_air_damper,
  cooling_valve,
  CASE
    -- Implement FC12 against assigned Haystack → FDD columns
    -- NULL samples must not latch faults
    WHEN false THEN false  -- stub: never latch until equation is coded
    ELSE false
  END AS fault_raw
FROM telemetry_pivot
WHERE equipment_id = 'equip:your-id'
```

### FC13 — SAT above SP at full cooling (GL36 K)
**Family:** `ahu` · **Equipment:** `ahu`  
**Equation:** SATavg > SATSP + εSAT AND CC ≥ full-cooling threshold in OS#3/OS#4.  
**Default confirmation:** 600 s

| Param | Label | Unit | Default | Range |
|-------|-------|------|--------:|-------|
| `eps_sat` | SAT sensor error εSAT (GL36 default 2°F) | °F | 1.0 | 0.0–10.0 |
| `sat_err` | Legacy SAT error (sets εSAT) | °F | 1.0 | 0.0–10.0 |
| `clg_full_min` | Full-cooling threshold (GL36 99%) | frac | 0.01 | 0.5–1.0 |
| `econ_min_pos` | Economizer minimum-position threshold | frac | 0.05 | 0.0–0.5 |
| `econ_full_open` | Economizer full-open threshold | frac | 0.9 | 0.5–1.0 |
| `mode_delay_min` | Mode-change suspension (GL36 default 30) | min | 0.0 | 0.0–60.0 |

```sql
-- confirmation_seconds: 600
-- rule: FC13 — SAT above SP at full cooling (GL36 K)
-- equation: CHW > 1%, SAT > SAT SP + 1.0°F at min or full economizer.

SELECT
  timestamp,
  equipment_id,
  discharge_air_temp,
  discharge_air_temp_sp,
  outside_air_damper,
  cooling_valve,
  CASE
    -- Implement FC13 against assigned Haystack → FDD columns
    -- NULL samples must not latch faults
    WHEN false THEN false  -- stub: never latch until equation is coded
    ELSE false
  END AS fault_raw
FROM telemetry_pivot
WHERE equipment_id = 'equip:your-id'
```

### FC14 — CHW coil ΔT when inactive (GL36 L)
**Family:** `ahu` · **Equipment:** `ahu`  
**Equation:** Cooling-coil ΔT ≥ √(εCCET² + εCCLT²) + ΔTSF while coil should be inactive.  
**Default confirmation:** 600 s

| Param | Label | Unit | Default | Range |
|-------|-------|------|--------:|-------|
| `eps_ccet` | Cooling-coil entering sensor error εCCET | °F | 1.15 | 0.0–10.0 |
| `eps_cclt` | Cooling-coil leaving sensor error εCCLT | °F | 1.15 | 0.0–10.0 |
| `delta_supply_fan` | Supply-fan heat rise ΔTSF (GL36 default 2°F) | °F | 0.55 | 0.0–5.0 |
| `econ_min_pos` | Economizer minimum-position threshold | frac | 0.05 | 0.0–0.5 |
| `clg_inactive_max` | Cooling-command inactive ceiling | frac | 0.1 | 0.0–0.5 |
| `htg_on_min` | Heating-command ON threshold | frac | 0.01 | 0.0–0.25 |
| `mix_tol` | Legacy master sensor tolerance (sets all ε values) | °F | 1.15 | 0.0–10.0 |
| `mode_delay_min` | Mode-change suspension (GL36 default 30) | min | 0.0 | 0.0–60.0 |

```sql
-- confirmation_seconds: 600
-- rule: FC14 — CHW coil ΔT when inactive (GL36 L)
-- equation: Cooling coil ΔT ≥ √(mix_tol²+mix_tol²)+0.55°F while coil should be inactive.

SELECT
  timestamp,
  equipment_id,
  cooling_coil_entering_temp,
  cooling_coil_leaving_temp,
  outside_air_damper,
  cooling_valve,
  CASE
    -- Implement FC14 against assigned Haystack → FDD columns
    -- NULL samples must not latch faults
    WHEN false THEN false  -- stub: never latch until equation is coded
    ELSE false
  END AS fault_raw
FROM telemetry_pivot
WHERE equipment_id = 'equip:your-id'
```

### FC15 — HW coil ΔT when inactive (GL36 M)
**Family:** `ahu` · **Equipment:** `ahu`  
**Equation:** Heating-coil ΔT ≥ √(εHCET² + εHCLT²) + ΔTSF while coil should be inactive.  
**Default confirmation:** 600 s

| Param | Label | Unit | Default | Range |
|-------|-------|------|--------:|-------|
| `eps_hcet` | Heating-coil entering sensor error εHCET | °F | 1.15 | 0.0–10.0 |
| `eps_hclt` | Heating-coil leaving sensor error εHCLT | °F | 1.15 | 0.0–10.0 |
| `delta_supply_fan` | Supply-fan heat rise ΔTSF (GL36 default 2°F) | °F | 0.55 | 0.0–5.0 |
| `econ_min_pos` | Economizer minimum-position threshold | frac | 0.05 | 0.0–0.5 |
| `econ_full_open` | Economizer full-open threshold | frac | 0.9 | 0.5–1.0 |
| `clg_inactive_max` | Cooling-command inactive ceiling | frac | 0.1 | 0.0–0.5 |
| `clg_on_min` | Cooling-command ON threshold | frac | 0.01 | 0.0–0.25 |
| `mix_tol` | Legacy master sensor tolerance (sets all ε values) | °F | 1.15 | 0.0–10.0 |
| `mode_delay_min` | Mode-change suspension (GL36 default 30) | min | 0.0 | 0.0–60.0 |

```sql
-- confirmation_seconds: 600
-- rule: FC15 — HW coil ΔT when inactive (GL36 M)
-- equation: Heating coil ΔT ≥ √(mix_tol²+mix_tol²)+0.55°F while coil should be inactive.

SELECT
  timestamp,
  equipment_id,
  heating_coil_entering_temp,
  heating_coil_leaving_temp,
  outside_air_damper,
  cooling_valve,
  CASE
    -- Implement FC15 against assigned Haystack → FDD columns
    -- NULL samples must not latch faults
    WHEN false THEN false  -- stub: never latch until equation is coded
    ELSE false
  END AS fault_raw
FROM telemetry_pivot
WHERE equipment_id = 'equip:your-id'
```

### AHU-SATDEV — SAT deviation from setpoint
**Family:** `ahu` · **Equipment:** `ahu`  
**Equation:** |SAT − SAT SP| > 5°F.  
**Default confirmation:** 600 s

| Param | Label | Unit | Default | Range |
|-------|-------|------|--------:|-------|
| `sat_dev_err` | SAT deviation | °F | 5.0 | 1.0–15.0 |

```sql
-- confirmation_seconds: 600
-- rule: AHU-SATDEV — SAT deviation from setpoint
-- equation: |SAT − SAT SP| > 5°F.

SELECT
  timestamp,
  equipment_id,
  discharge_air_temp,
  discharge_air_temp_sp,
  CASE
    -- Implement AHU-SATDEV against assigned Haystack → FDD columns
    -- NULL samples must not latch faults
    WHEN false THEN false  -- stub: never latch until equation is coded
    ELSE false
  END AS fault_raw
FROM telemetry_pivot
WHERE equipment_id = 'equip:your-id'
```

### AHU-DUCTHI — Duct static pressure high
**Family:** `ahu` · **Equipment:** `ahu`  
**Equation:** Duct static > static SP + margin. Evaluates when fan is proven on OR duct static itself exceeds pressure_on_min (catches high static with fan-status off).  
**Default confirmation:** 300 s

| Param | Label | Unit | Default | Range |
|-------|-------|------|--------:|-------|
| `duct_high_margin` | High margin | in. w.c. | 0.25 | 0.05–1.0 |
| `pressure_on_min` | Pressure-on evidence | in. w.c. | 0.2 | 0.05–1.0 |

```sql
-- confirmation_seconds: 300
-- rule: AHU-DUCTHI — Duct static pressure high
-- equation: Duct static > static SP + margin. Evaluates when fan is proven on OR duct static itself exceeds pressure_on_min (catches high static with fan-status off).

SELECT
  timestamp,
  equipment_id,
  duct_static_pressure,
  duct_static_pressure_sp,
  CASE
    -- Implement AHU-DUCTHI against assigned Haystack → FDD columns
    -- NULL samples must not latch faults
    WHEN false THEN false  -- stub: never latch until equation is coded
    ELSE false
  END AS fault_raw
FROM telemetry_pivot
WHERE equipment_id = 'equip:your-id'
```

### AHU-SIMUL — Heating and cooling simultaneous
**Family:** `ahu` · **Equipment:** `ahu`  
**Equation:** Heating valve > 10% AND cooling valve > 10% at once.  
**Default confirmation:** 300 s

| Param | Label | Unit | Default | Range |
|-------|-------|------|--------:|-------|
| `valve_open_pct` | Valve open threshold | frac | 0.1 | 0.05–0.5 |

```sql
-- confirmation_seconds: 300
-- rule: AHU-SIMUL — Heating and cooling simultaneous
-- equation: Heating valve > 10% AND cooling valve > 10% at once.

SELECT
  timestamp,
  equipment_id,
  heating_valve,
  cooling_valve,
  CASE
    -- Implement AHU-SIMUL against assigned Haystack → FDD columns
    -- NULL samples must not latch faults
    WHEN false THEN false  -- stub: never latch until equation is coded
    ELSE false
  END AS fault_raw
FROM telemetry_pivot
WHERE equipment_id = 'equip:your-id'
```

### OAT-METEO — BAS outdoor-air sensor vs Open-Meteo
**Family:** `ahu` · **Equipment:** `ahu`  
**Equation:** BAS OAT sensor differs from Open-Meteo dry bulb by more than 5°F.  
**Default confirmation:** 900 s

| Param | Label | Unit | Default | Range |
|-------|-------|------|--------:|-------|
| `oat_err` | Max OAT disagreement | °F | 5.0 | 2.0–20.0 |

```sql
-- confirmation_seconds: 900
-- param: oat_err = 5.0
SELECT
  timestamp, equipment_id, oa_t, oat_meteo,
  CASE
    WHEN oa_t IS NULL OR oat_meteo IS NULL THEN false
    WHEN abs(oa_t - oat_meteo) > 5.0 THEN true
    ELSE false
  END AS fault_raw
FROM telemetry_pivot
WHERE equipment_id = 'equip:your-ahu'
```


### ECON-1 — Economizer stuck closed
**Family:** `ahu` · **Equipment:** `ahu`  
**Equation:** Fan on, OA damper < 5%, OAT > 55°F (should be economizing).  
**Default confirmation:** 600 s

| Param | Label | Unit | Default | Range |
|-------|-------|------|--------:|-------|
| `econ1_oat_min` | Favorable OAT | °F | 55.0 | 45.0–70.0 |

```sql
-- confirmation_seconds: 600
SELECT
  timestamp, equipment_id, oa_damper_pct, oa_t, mat, rat, fan_cmd,
  CASE
    WHEN oa_damper_pct IS NULL OR mat IS NULL OR oa_t IS NULL THEN false
    WHEN (CASE WHEN oa_damper_pct > 1.0 THEN oa_damper_pct / 100.0 ELSE oa_damper_pct END) <= 0.05
     AND abs(mat - oa_t) > 5.0
     AND (CASE WHEN fan_cmd > 1.0 THEN fan_cmd / 100.0 ELSE fan_cmd END) >= 0.05 THEN true
    ELSE false
  END AS fault_raw
FROM telemetry_pivot
WHERE equipment_id = 'equip:your-ahu'
```

### ECON-2 — Economizing when outdoor unfavorable
**Family:** `ahu` · **Equipment:** `ahu`  
**Equation:** OAT > 63°F AND OA damper > 42% (should be at minimum).  
**Default confirmation:** 300 s

| Param | Label | Unit | Default | Range |
|-------|-------|------|--------:|-------|
| `econ2_oat_hi` | OAT high cutoff | °F | 63.0 | 55.0–80.0 |
| `econ2_damper` | Damper open frac | frac | 0.42 | 0.2–0.9 |

```sql
-- confirmation_seconds: 300
-- rule: ECON-2 — Economizing when outdoor unfavorable
-- equation: OAT > 63°F AND OA damper > 42% (should be at minimum).

SELECT
  timestamp,
  equipment_id,
  outside_air_temp,
  outside_air_damper,
  CASE
    -- Implement ECON-2 against assigned Haystack → FDD columns
    -- NULL samples must not latch faults
    WHEN false THEN false  -- stub: never latch until equation is coded
    ELSE false
  END AS fault_raw
FROM telemetry_pivot
WHERE equipment_id = 'equip:your-id'
```

### ECON-3 — Mech cooling without integrated economizer
**Family:** `ahu` · **Equipment:** `ahu`  
**Equation:** Web free-cooling opportunity (60°F ≤ DB < 72°F AND dewpoint < 60°F) while cooling valve open and OA damper below integrated threshold (default 90%).  
**Default confirmation:** 300 s

| Param | Label | Unit | Default | Range |
|-------|-------|------|--------:|-------|
| `econ3_db_min` | Free-cool OA dry-bulb min | °F | 60.0 | 50.0–68.0 |
| `econ3_db_max` | Free-cool OA dry-bulb max | °F | 72.0 | 65.0–80.0 |
| `econ3_dp_max` | Free-cool OA dew point max | °F | 60.0 | 45.0–68.0 |
| `econ3_damper_hi` | Integrated economizer damper | frac | 0.9 | 0.5–1.0 |

```sql
-- confirmation_seconds: 300
SELECT
  timestamp, equipment_id, web_oa_t, web_oa_dp, oa_damper_pct, clg_valve_pct,
  CASE
    WHEN web_oa_t IS NULL OR web_oa_dp IS NULL OR oa_damper_pct IS NULL OR clg_valve_pct IS NULL THEN false
    WHEN web_oa_t >= 60.0 AND web_oa_t < 72.0 AND web_oa_dp < 60.0
     AND (CASE WHEN clg_valve_pct > 1.0 THEN clg_valve_pct / 100.0 ELSE clg_valve_pct END) > 0.01
     AND (CASE WHEN oa_damper_pct > 1.0 THEN oa_damper_pct / 100.0 ELSE oa_damper_pct END) < 0.90 THEN true
    ELSE false
  END AS fault_raw
FROM telemetry_pivot
WHERE equipment_id = 'equip:your-ahu'
```


### ECON-4 — Low estimated OA fraction
**Family:** `ahu` · **Equipment:** `ahu`  
**Equation:** Fan on, |RAT−OAT| > 2.2°F, estimated OA fraction < 21%.  
**Default confirmation:** 600 s

| Param | Label | Unit | Default | Range |
|-------|-------|------|--------:|-------|
| `oa_min_pct` | Min OA fraction | % | 21.0 | 5.0–40.0 |

```sql
-- confirmation_seconds: 600
-- rule: ECON-4 — Low estimated OA fraction
-- equation: Fan on, |RAT−OAT| > 2.2°F, estimated OA fraction < 21%.

SELECT
  timestamp,
  equipment_id,
  mixed_air_temp,
  return_air_temp,
  outside_air_temp,
  fan_cmd,
  CASE
    -- Implement ECON-4 against assigned Haystack → FDD columns
    -- NULL samples must not latch faults
    WHEN false THEN false  -- stub: never latch until equation is coded
    ELSE false
  END AS fault_raw
FROM telemetry_pivot
WHERE equipment_id = 'equip:your-id'
```

### ECON-5 — Preheat over-conditioning
**Family:** `ahu` · **Equipment:** `ahu`  
**Equation:** Preheat leaving air > 2.2°F above target while preheat active.  
**Default confirmation:** 600 s

| Param | Label | Unit | Default | Range |
|-------|-------|------|--------:|-------|
| `preheat_over_f` | Preheat over ΔT | °F | 2.2 | 0.5–8.0 |

```sql
-- confirmation_seconds: 600
-- rule: ECON-5 — Preheat over-conditioning
-- equation: Preheat leaving air > 2.2°F above target while preheat active.

SELECT
  timestamp,
  equipment_id,
  preheat_leaving_temp,
  discharge_air_temp_sp,
  outside_air_temp,
  heating_valve,
  CASE
    -- Implement ECON-5 against assigned Haystack → FDD columns
    -- NULL samples must not latch faults
    WHEN false THEN false  -- stub: never latch until equation is coded
    ELSE false
  END AS fault_raw
FROM telemetry_pivot
WHERE equipment_id = 'equip:your-id'
```

### ECON-6 — Economizing in freezing weather
**Family:** `ahu` · **Equipment:** `ahu`  
**Equation:** Web dry-bulb < 25°F AND OA damper above winter min-OA ceiling (default 25%). AHU should be at minimum OA in cold weather.  
**Default confirmation:** 600 s

| Param | Label | Unit | Default | Range |
|-------|-------|------|--------:|-------|
| `econ6_oat_max_f` | Winter OAT ceiling | °F | 25.0 | 15.0–40.0 |
| `econ6_damper_max` | Winter min-OA damper | frac | 0.25 | 0.05–0.5 |

```sql
-- confirmation_seconds: 600
-- rule: ECON-6 — Economizing in freezing weather
-- equation: Web dry-bulb < 25°F AND OA damper above winter min-OA ceiling (default 25%). AHU should be at minimum OA in cold weather.

SELECT
  timestamp,
  equipment_id,
  outside_air_damper,
  CASE
    -- Implement ECON-6 against assigned Haystack → FDD columns
    -- NULL samples must not latch faults
    WHEN false THEN false  -- stub: never latch until equation is coded
    ELSE false
  END AS fault_raw
FROM telemetry_pivot
WHERE equipment_id = 'equip:your-id'
```

### ECON-7 — Economizer OK but not economizing
**Family:** `ahu` · **Equipment:** `ahu`  
**Equation:** Economizer-OK web weather: dew point < 60°F AND dry-bulb < 72°F (above a 35°F freeze-guard floor; dewpoint from web sensor or calculated from web DB+RH). Fault when there is cooling demand (cooling valve open or proven DX/chiller cooling) but the OA damper stays below the economizing threshold (default 50%). Expected: economizer-only below 60°F DB (MECH-OAT-1) and mech + integrated economizer in the 60–72°F band (ECON-3). All thresholds are imperial sliders.  
**Default confirmation:** 600 s

| Param | Label | Unit | Default | Range |
|-------|-------|------|--------:|-------|
| `econ7_db_min` | Econ-OK dry-bulb floor (freeze guard) | °F | 35.0 | 20.0–50.0 |
| `econ7_db_max` | Econ-OK dry-bulb max | °F | 72.0 | 65.0–80.0 |
| `econ7_dp_max` | Econ-OK dew point max | °F | 60.0 | 45.0–68.0 |
| `econ7_damper_min` | Economizing damper threshold | frac | 0.5 | 0.2–0.9 |

```sql
-- confirmation_seconds: 600
-- rule: ECON-7 — Economizer OK but not economizing
-- equation: Economizer-OK web weather: dew point < 60°F AND dry-bulb < 72°F (above a 35°F freeze-guard floor; dewpoint from web sensor or calculated from web DB+RH). Fault when there is cooling demand (cooling valve open or proven DX/chiller cooling) but the OA damper stays below the economizing threshold (default 50%). Expected: economizer-only below 60°F DB (MECH-OAT-1) and mech + integrated economizer in the 60–72°F band (ECON-3). All thresholds are imperial sliders.

SELECT
  timestamp,
  equipment_id,
  outside_air_damper,
  CASE
    -- Implement ECON-7 against assigned Haystack → FDD columns
    -- NULL samples must not latch faults
    WHEN false THEN false  -- stub: never latch until equation is coded
    ELSE false
  END AS fault_raw
FROM telemetry_pivot
WHERE equipment_id = 'equip:your-id'
```

### MECH-OAT-1 — Mechanical cooling below 60°F web OAT
**Family:** `ahu` · **Equipment:** `ahu`, `chiller`, `heatpump`  
**Equation:** Proven DX/chiller mechanical cooling while web dry-bulb < 60°F. Uses compressor/chiller/pump/amps/power proof — not AHU cooling-valve alone. Below 60°F is outside the free-cool + integrated economizer band.  
**Default confirmation:** 600 s

| Param | Label | Unit | Default | Range |
|-------|-------|------|--------:|-------|
| `mech_oat_max_f` | Mech-cool OAT ceiling | °F | 60.0 | 45.0–65.0 |

```sql
-- confirmation_seconds: 600
-- rule: MECH-OAT-1 — Mechanical cooling below 60°F web OAT
-- equation: Proven DX/chiller mechanical cooling while web dry-bulb < 60°F. Uses compressor/chiller/pump/amps/power proof — not AHU cooling-valve alone. Below 60°F is outside the free-cool + integrated economizer band.

SELECT
  timestamp,
  equipment_id,
  CASE
    -- Implement MECH-OAT-1 against assigned Haystack → FDD columns
    -- NULL samples must not latch faults
    WHEN false THEN false  -- stub: never latch until equation is coded
    ELSE false
  END AS fault_raw
FROM telemetry_pivot
WHERE equipment_id = 'equip:your-id'
```

### CMD-1 — Fan cmd/status mismatch
**Family:** `ahu` · **Equipment:** `ahu`  
**Equation:** Fan command and proven status disagree.  
**Default confirmation:** 600 s

_No tunable thresholds beyond confirmation delay._

```sql
-- confirmation_seconds: 600
SELECT
  timestamp, equipment_id, fan_cmd, fan_status,
  CASE
    WHEN fan_cmd IS NULL OR fan_status IS NULL THEN false
    WHEN ((CASE WHEN fan_cmd > 1.0 THEN fan_cmd / 100.0 ELSE fan_cmd END) >= 0.05) <> fan_status THEN true
    ELSE false
  END AS fault_raw
FROM telemetry_pivot
WHERE equipment_id = 'equip:your-ahu'
```

### OA-1 — Low OA fraction
**Family:** `ahu` · **Equipment:** `ahu`  
**Equation:** Estimated OA fraction < 15% with adequate OAT/RAT split.  
**Default confirmation:** 900 s

| Param | Label | Unit | Default | Range |
|-------|-------|------|--------:|-------|
| `min_oa_frac` | Min OA fraction | frac | 0.15 | 0.05–0.4 |
| `oat_rat_guard` | Min |RAT−OAT| guard | °F | 2.2 | 0.5–6.0 |

```sql
-- confirmation_seconds: 900
-- param: min_oa_frac = 0.15 ; oat_rat_guard = 2.2
SELECT
  timestamp, equipment_id, mat, rat, oa_t, fan_cmd,
  CASE
    WHEN mat IS NULL OR rat IS NULL OR oa_t IS NULL THEN false
    WHEN abs(rat - oa_t) <= 2.2 THEN false
    WHEN (mat - rat) / NULLIF(oa_t - rat, 0) < 0.15
     AND (CASE WHEN fan_cmd > 1.0 THEN fan_cmd / 100.0 ELSE fan_cmd END) >= 0.05 THEN true
    ELSE false
  END AS fault_raw
FROM telemetry_pivot
WHERE equipment_id = 'equip:your-ahu'
```

### DMP-1 — OA damper leakage
**Family:** `ahu` · **Equipment:** `ahu`  
**Equation:** Damper ≤ 5% but MAT tracks OAT within 2°F — leaking OA damper.  
**Default confirmation:** 900 s

| Param | Label | Unit | Default | Range |
|-------|-------|------|--------:|-------|
| `leak_delta` | Leak ΔT | °F | 2.0 | 0.5–6.0 |

```sql
-- confirmation_seconds: 900
SELECT
  timestamp, equipment_id, oa_damper_pct, oa_t, mat,
  CASE
    WHEN oa_damper_pct IS NULL OR oa_t IS NULL OR mat IS NULL THEN false
    WHEN (CASE WHEN oa_damper_pct > 1.0 THEN oa_damper_pct / 100.0 ELSE oa_damper_pct END) <= 0.05
     AND abs(mat - oa_t) < 2.0 THEN true
    ELSE false
  END AS fault_raw
FROM telemetry_pivot
WHERE equipment_id = 'equip:your-ahu'
```

### VLV-1 — Cooling valve leakage
**Family:** `ahu` · **Equipment:** `ahu`  
**Equation:** Cooling valve ≤ 5% AND (SAT < sat_sp − sat_err OR SAT < MAT − mat_leak_delta). Fan proven on when fan_status/fan_cmd present (operational gate).  
**Default confirmation:** 900 s

| Param | Label | Unit | Default | Range |
|-------|-------|------|--------:|-------|
| `sat_err` | SAT vs SP leak ΔT | °F | 2.0 | 0.5–8.0 |
| `mat_leak_delta` | SAT vs MAT leak ΔT | °F | 2.0 | 0.5–12.0 |

```sql
-- confirmation_seconds: 900
SELECT
  timestamp, equipment_id, clg_valve_pct, sat, sat_sp, mat,
  CASE
    WHEN clg_valve_pct IS NULL OR sat IS NULL THEN false
    WHEN (CASE WHEN clg_valve_pct > 1.0 THEN clg_valve_pct / 100.0 ELSE clg_valve_pct END) <= 0.05
     AND (
       (sat_sp IS NOT NULL AND sat < sat_sp - 2.0)
       OR (mat IS NOT NULL AND sat < mat - 2.0)
     ) THEN true
    ELSE false
  END AS fault_raw
FROM telemetry_pivot
WHERE equipment_id = 'equip:your-ahu'
```

## VAV terminals

### VAV-1 — Zone comfort band
**Family:** `vav` · **Equipment:** `vav`, `zone`  
**Equation:** Zone temp < 70°F or > 75°F.  
**Default confirmation:** 900 s

| Param | Label | Unit | Default | Range |
|-------|-------|------|--------:|-------|
| `zone_lo` | Zone low | °F | 70.0 | 55.0–72.0 |
| `zone_hi` | Zone high | °F | 75.0 | 72.0–85.0 |

```sql
-- confirmation_seconds: 900
-- param: comfort_low_f = 70 ; comfort_high_f = 75
SELECT
  timestamp, equipment_id, zone_t, occ_mode,
  CASE
    WHEN zone_t IS NULL THEN false
    WHEN lower(COALESCE(occ_mode, 'occupied')) = 'occupied'
     AND (zone_t < 70.0 OR zone_t > 75.0) THEN true
    ELSE false
  END AS fault_raw
FROM telemetry_pivot
WHERE equipment_id = 'equip:your-vav'
```

### VAV-3 — Excessive reheat during warm weather
**Family:** `vav` · **Equipment:** `vav`  
**Equation:** Air flowing AND OAT > 78°F AND reheat valve > 52%.  
**Default confirmation:** 300 s

| Param | Label | Unit | Default | Range |
|-------|-------|------|--------:|-------|
| `reheat_oat` | Warm OAT | °F | 78.0 | 65.0–90.0 |
| `reheat_pct` | Reheat frac | frac | 0.52 | 0.1–1.0 |
| `flow_on_min` | Airflow-on min | cfm | 25.0 | 0.0–200.0 |

```sql
-- confirmation_seconds: 300
-- rule: VAV-3 — Excessive reheat during warm weather
-- equation: Air flowing AND OAT > 78°F AND reheat valve > 52%.

SELECT
  timestamp,
  equipment_id,
  outside_air_temp,
  reheat_valve,
  CASE
    -- Implement VAV-3 against assigned Haystack → FDD columns
    -- NULL samples must not latch faults
    WHEN false THEN false  -- stub: never latch until equation is coded
    ELSE false
  END AS fault_raw
FROM telemetry_pivot
WHERE equipment_id = 'equip:your-id'
```

### VAV-4 — Damper stuck at full open
**Family:** `vav` · **Equipment:** `vav`  
**Equation:** Air flowing AND damper > 97.5% sustained across the window.  
**Default confirmation:** 900 s

| Param | Label | Unit | Default | Range |
|-------|-------|------|--------:|-------|
| `full_open_pct` | Full open frac | frac | 0.975 | 0.8–1.0 |
| `sustain_hours` | Sustain window | h | 1.5 | 0.5–6.0 |
| `flow_on_min` | Airflow-on min | cfm | 25.0 | 0.0–200.0 |

```sql
-- confirmation_seconds: 900
-- rule: VAV-4 — Damper stuck at full open
-- equation: Air flowing AND damper > 97.5% sustained across the window.

SELECT
  timestamp,
  equipment_id,
  damper,
  CASE
    -- Implement VAV-4 against assigned Haystack → FDD columns
    -- NULL samples must not latch faults
    WHEN false THEN false  -- stub: never latch until equation is coded
    ELSE false
  END AS fault_raw
FROM telemetry_pivot
WHERE equipment_id = 'equip:your-id'
```

### VAV-5 — Airflow sensor bias
**Family:** `vav` · **Equipment:** `vav`  
**Equation:** Airflow > 50 cfm while damper < 10% (implausible flow).  
**Default confirmation:** 900 s

_No tunable thresholds beyond confirmation delay._

```sql
-- confirmation_seconds: 900
-- rule: VAV-5 — Airflow sensor bias
-- equation: Airflow > 50 cfm while damper < 10% (implausible flow).

SELECT
  timestamp,
  equipment_id,
  zone_airflow,
  damper,
  CASE
    -- Implement VAV-5 against assigned Haystack → FDD columns
    -- NULL samples must not latch faults
    WHEN false THEN false  -- stub: never latch until equation is coded
    ELSE false
  END AS fault_raw
FROM telemetry_pivot
WHERE equipment_id = 'equip:your-id'
```

### VAV-REHEAT — Reheat valve stuck / no temp rise
**Family:** `vav` · **Equipment:** `vav`  
**Equation:** Air flowing AND reheat valve > 30% AND box discharge temp rises < 3°F above duct inlet (air from AHU) — stuck or failed reheat valve/coil.  
**Default confirmation:** 900 s

| Param | Label | Unit | Default | Range |
|-------|-------|------|--------:|-------|
| `reheat_cmd` | Reheat open frac | frac | 0.3 | 0.1–1.0 |
| `min_rise` | Min temp rise | °F | 3.0 | 0.5–15.0 |
| `flow_on_min` | Airflow-on min | cfm | 25.0 | 0.0–200.0 |

```sql
-- confirmation_seconds: 900
-- rule: VAV-REHEAT — Reheat valve stuck / no temp rise
-- equation: Air flowing AND reheat valve > 30% AND box discharge temp rises < 3°F above duct inlet (air from AHU) — stuck or failed reheat valve/coil.

SELECT
  timestamp,
  equipment_id,
  reheat_valve,
  vav_discharge_air_temp,
  vav_inlet_air_temp,
  CASE
    -- Implement VAV-REHEAT against assigned Haystack → FDD columns
    -- NULL samples must not latch faults
    WHEN false THEN false  -- stub: never latch until equation is coded
    ELSE false
  END AS fault_raw
FROM telemetry_pivot
WHERE equipment_id = 'equip:your-id'
```

### VAV-AHU-LEAVE — VAV leave vs parent AHU SAT (fedBy)
**Family:** `vav` · **Equipment:** `vav`  
**Equation:** Air flowing AND |VAV discharge − parent AHU SAT| > band. Needs package topology (vav_to_ahu) so ahu_sat is enriched from the fedBy AHU; otherwise SKIPPED_MISSING_ROLES. Flags broken reheat, bad sensors, or rogue zones.  
**Default confirmation:** 900 s

| Param | Label | Unit | Default | Range |
|-------|-------|------|--------:|-------|
| `delta_f` | Leave Δ vs AHU SAT | °F | 8.0 | 2.0–25.0 |
| `flow_on_min` | Airflow-on min | cfm | 25.0 | 0.0–200.0 |

```sql
-- confirmation_seconds: 900
-- rule: VAV-AHU-LEAVE — VAV leave vs parent AHU SAT (fedBy)
-- equation: Air flowing AND |VAV discharge − parent AHU SAT| > band. Needs package topology (vav_to_ahu) so ahu_sat is enriched from the fedBy AHU; otherwise SKIPPED_MISSING_ROLES. Flags broken reheat, bad sensors, or rogue zones.

SELECT
  timestamp,
  equipment_id,
  vav_discharge_air_temp,
  ahu_discharge_air_temp,
  CASE
    -- Implement VAV-AHU-LEAVE against assigned Haystack → FDD columns
    -- NULL samples must not latch faults
    WHEN false THEN false  -- stub: never latch until equation is coded
    ELSE false
  END AS fault_raw
FROM telemetry_pivot
WHERE equipment_id = 'equip:your-id'
```

### VAV-7 — Min airflow / fixed high flow
**Family:** `vav` · **Equipment:** `vav`  
**Equation:** Flow below min SP (when mapped), OR airflow stays flat (low rolling std) at a high mean while air is on (mins too high / box never modulates), OR min_flow_sp itself is excessively high.  
**Default confirmation:** 900 s

| Param | Label | Unit | Default | Range |
|-------|-------|------|--------:|-------|
| `flow_on_min` | Airflow-on min | cfm | 25.0 | 0.0–200.0 |
| `fixed_flow_max_std` | Fixed-flow max std | cfm | 15.0 | 1.0–80.0 |
| `fixed_flow_min_mean` | Fixed-flow min mean | cfm | 200.0 | 50.0–2000.0 |
| `high_min_flow_sp` | High min-flow SP | cfm | 250.0 | 50.0–2000.0 |

```sql
-- confirmation_seconds: 900
SELECT
  timestamp, equipment_id, zone_flow, min_flow_sp,
  CASE
    WHEN zone_flow IS NULL OR min_flow_sp IS NULL THEN false
    WHEN zone_flow < min_flow_sp THEN true
    ELSE false
  END AS fault_raw
FROM telemetry_pivot
WHERE equipment_id = 'equip:your-vav'
```

## Central plant / condenser water

### CHW-NOLOAD-1 — Chiller running with no building load
**Family:** `plant` · **Equipment:** `chiller`  
**Equation:** Chiller/plant proven running while building load is satisfied: all mapped zones inside comfort band OR all mapped AHU SAT within sat_band of setpoint. Default confirm 30 min.  
**Default confirmation:** 1800 s

| Param | Label | Unit | Default | Range |
|-------|-------|------|--------:|-------|
| `comfort_low_f` | Comfort low | °F | 70.0 | 60.0–78.0 |
| `comfort_high_f` | Comfort high | °F | 75.0 | 68.0–85.0 |
| `sat_band_f` | AHU SAT≈SP band | °F | 2.0 | 0.5–6.0 |

```sql
-- confirmation_seconds: 1800
-- rule: CHW-NOLOAD-1 — Chiller running with no building load
-- equation: Chiller/plant proven running while building load is satisfied: all mapped zones inside comfort band OR all mapped AHU SAT within sat_band of setpoint. Default confirm 30 min.

SELECT
  timestamp,
  equipment_id,
  CASE
    -- Implement CHW-NOLOAD-1 against assigned Haystack → FDD columns
    -- NULL samples must not latch faults
    WHEN false THEN false  -- stub: never latch until equation is coded
    ELSE false
  END AS fault_raw
FROM telemetry_pivot
WHERE equipment_id = 'equip:your-id'
```

### CHW-1 — Low chilled-water ΔT
**Family:** `plant` · **Equipment:** `chiller`  
**Equation:** Pump on AND (CHWR − CHWS) < 4°F.  
**Default confirmation:** 900 s

| Param | Label | Unit | Default | Range |
|-------|-------|------|--------:|-------|
| `min_dt` | Min ΔT | °F | 4.0 | 1.0–12.0 |

```sql
-- confirmation_seconds: 900
-- param: min_dt = 4.0
SELECT
  timestamp, equipment_id, chw_supply_t, chw_return_t, chw_pump_cmd,
  CASE
    WHEN chw_supply_t IS NULL OR chw_return_t IS NULL THEN false
    WHEN chw_pump_cmd IS NOT NULL
     AND (CASE WHEN chw_pump_cmd > 1.0 THEN chw_pump_cmd / 100.0 ELSE chw_pump_cmd END) <= 0.05 THEN false
    WHEN (chw_return_t - chw_supply_t) < 4.0 THEN true
    ELSE false
  END AS fault_raw
FROM telemetry_pivot
WHERE equipment_id = 'equip:your-chw-plant'
```


### CHW-2 — DP below SP at max pump speed
**Family:** `plant` · **Equipment:** `chiller`  
**Equation:** Pump ≥ 87% AND CHW DP < DP SP − 2.2.  
**Default confirmation:** 300 s

| Param | Label | Unit | Default | Range |
|-------|-------|------|--------:|-------|
| `dp_margin` | DP margin | psi | 2.2 | 0.5–6.0 |
| `pump_hi` | Pump high-speed threshold | frac | 0.87 | 0.5–1.0 |

```sql
-- confirmation_seconds: 300
-- rule: CHW-2 — DP below SP at max pump speed
-- equation: Pump ≥ 87% AND CHW DP < DP SP − 2.2.

SELECT
  timestamp,
  equipment_id,
  chw_diff_pressure,
  chw_diff_pressure_sp,
  chw_pump_cmd,
  CASE
    -- Implement CHW-2 against assigned Haystack → FDD columns
    -- NULL samples must not latch faults
    WHEN false THEN false  -- stub: never latch until equation is coded
    ELSE false
  END AS fault_raw
FROM telemetry_pivot
WHERE equipment_id = 'equip:your-id'
```

### CHW-3 — Plant supply temp outside deadband
**Family:** `plant` · **Equipment:** `chiller`  
**Equation:** Pump on AND |CHWS − CHWS SP| > 2.2°F.  
**Default confirmation:** 300 s

| Param | Label | Unit | Default | Range |
|-------|-------|------|--------:|-------|
| `sp_band` | SP band | °F | 2.2 | 0.5–6.0 |

```sql
-- confirmation_seconds: 300
-- rule: CHW-3 — Plant supply temp outside deadband
-- equation: Pump on AND |CHWS − CHWS SP| > 2.2°F.

SELECT
  timestamp,
  equipment_id,
  chilled_water_supply_temp,
  chilled_water_supply_temp_sp,
  chw_pump_cmd,
  CASE
    -- Implement CHW-3 against assigned Haystack → FDD columns
    -- NULL samples must not latch faults
    WHEN false THEN false  -- stub: never latch until equation is coded
    ELSE false
  END AS fault_raw
FROM telemetry_pivot
WHERE equipment_id = 'equip:your-id'
```

### CHW-4 — Flow high at max pump
**Family:** `plant` · **Equipment:** `chiller`  
**Equation:** Pump ≥ 87% AND CHW flow > 1100 gpm.  
**Default confirmation:** 300 s

| Param | Label | Unit | Default | Range |
|-------|-------|------|--------:|-------|
| `flow_hi` | Flow high | gpm | 1100 | 200–3000 |
| `pump_hi` | Pump high-speed threshold | frac | 0.87 | 0.5–1.0 |

```sql
-- confirmation_seconds: 300
-- rule: CHW-4 — Flow high at max pump
-- equation: Pump ≥ 87% AND CHW flow > 1100 gpm.

SELECT
  timestamp,
  equipment_id,
  chw_flow,
  chw_pump_cmd,
  CASE
    -- Implement CHW-4 against assigned Haystack → FDD columns
    -- NULL samples must not latch faults
    WHEN false THEN false  -- stub: never latch until equation is coded
    ELSE false
  END AS fault_raw
FROM telemetry_pivot
WHERE equipment_id = 'equip:your-id'
```

### CW-OPT-1 — Condenser water not optimized vs wet-bulb
**Family:** `plant` · **Equipment:** `chiller`, `cooling_tower`  
**Equation:** CW supply significantly colder than web wet-bulb + design approach (Stull WB) — tower over-cooling / not optimized.  
**Default confirmation:** 900 s

| Param | Label | Unit | Default | Range |
|-------|-------|------|--------:|-------|
| `cw_approach` | Design approach | °F | 7.0 | 3.0–15.0 |
| `cw_slack` | Slack below target | °F | 2.0 | 0.5–6.0 |

```sql
-- confirmation_seconds: 900
-- rule: CW-OPT-1 — Condenser water not optimized vs wet-bulb
-- equation: CW supply significantly colder than web wet-bulb + design approach (Stull WB) — tower over-cooling / not optimized.

SELECT
  timestamp,
  equipment_id,
  condenser_water_supply_temp,
  CASE
    -- Implement CW-OPT-1 against assigned Haystack → FDD columns
    -- NULL samples must not latch faults
    WHEN false THEN false  -- stub: never latch until equation is coded
    ELSE false
  END AS fault_raw
FROM telemetry_pivot
WHERE equipment_id = 'equip:your-id'
```

### CW-APR-1 — High CW approach at full tower fan
**Family:** `plant` · **Equipment:** `chiller`, `cooling_tower`  
**Equation:** At full tower fan speed, leaving CW − web wet-bulb exceeds approach_max (default 8°F, typically 5–10°F). Suspect OA→wet-bulb / CW sensor mismatch or cooling-tower performance degradation.  
**Default confirmation:** 900 s

| Param | Label | Unit | Default | Range |
|-------|-------|------|--------:|-------|
| `approach_max_f` | Max approach at full fan | °F | 8.0 | 5.0–15.0 |
| `tower_fan_hi` | Tower fan full-speed threshold | frac | 0.95 | 0.8–1.0 |

```sql
-- confirmation_seconds: 900
-- rule: CW-APR-1 — High CW approach at full tower fan
-- equation: At full tower fan speed, leaving CW − web wet-bulb exceeds approach_max (default 8°F, typically 5–10°F). Suspect OA→wet-bulb / CW sensor mismatch or cooling-tower performance degradation.

SELECT
  timestamp,
  equipment_id,
  condenser_water_supply_temp,
  CASE
    -- Implement CW-APR-1 against assigned Haystack → FDD columns
    -- NULL samples must not latch faults
    WHEN false THEN false  -- stub: never latch until equation is coded
    ELSE false
  END AS fault_raw
FROM telemetry_pivot
WHERE equipment_id = 'equip:your-id'
```

### CW-FAN-1 — Excess tower fan energy vs wet-bulb limit
**Family:** `plant` · **Equipment:** `chiller`, `cooling_tower`  
**Equation:** Tower fans at full speed while leaving CW is well above web wet-bulb + design approach (approach + excess_beyond). Fans are chasing a CW temp that is theoretically hard/impossible — excess fan energy.  
**Default confirmation:** 900 s

| Param | Label | Unit | Default | Range |
|-------|-------|------|--------:|-------|
| `cw_approach` | Design approach | °F | 7.0 | 3.0–15.0 |
| `excess_beyond_approach_f` | Excess beyond approach | °F | 5.0 | 2.0–20.0 |
| `tower_fan_hi` | Tower fan full-speed threshold | frac | 0.95 | 0.8–1.0 |

```sql
-- confirmation_seconds: 900
-- rule: CW-FAN-1 — Excess tower fan energy vs wet-bulb limit
-- equation: Tower fans at full speed while leaving CW is well above web wet-bulb + design approach (approach + excess_beyond). Fans are chasing a CW temp that is theoretically hard/impossible — excess fan energy.

SELECT
  timestamp,
  equipment_id,
  condenser_water_supply_temp,
  CASE
    -- Implement CW-FAN-1 against assigned Haystack → FDD columns
    -- NULL samples must not latch faults
    WHEN false THEN false  -- stub: never latch until equation is coded
    ELSE false
  END AS fault_raw
FROM telemetry_pivot
WHERE equipment_id = 'equip:your-id'
```

## Heat pumps

### HP-1 — Discharge cold when heating
**Family:** `heatpump` · **Equipment:** `heatpump`  
**Equation:** Fan on, zone < 69°F, discharge SAT < 85°F.  
**Default confirmation:** 600 s

| Param | Label | Unit | Default | Range |
|-------|-------|------|--------:|-------|
| `min_sat` | Min heating SAT | °F | 85.0 | 70.0–110.0 |
| `zone_cold` | Zone cold | °F | 69.0 | 60.0–72.0 |

```sql
-- confirmation_seconds: 600
SELECT
  timestamp, equipment_id, sat, zone_t, fan_cmd,
  CASE
    WHEN sat IS NULL OR zone_t IS NULL OR fan_cmd IS NULL THEN false
    WHEN (CASE WHEN fan_cmd > 1.0 THEN fan_cmd / 100.0 ELSE fan_cmd END) >= 0.05
     AND zone_t < 69.0 AND sat < 85.0 THEN true
    ELSE false
  END AS fault_raw
FROM telemetry_pivot
WHERE equipment_id = 'equip:your-heatpump'
```


## Weather station

### WX-1 — OA temperature spike
**Family:** `weather` · **Equipment:** `weather`  
**Equation:** OAT sample-to-sample jump > 16°F.  
**Default confirmation:** 300 s

| Param | Label | Unit | Default | Range |
|-------|-------|------|--------:|-------|
| `spike_limit` | Spike limit | °F | 16.0 | 4.0–40.0 |

```sql
-- confirmation_seconds: 300
SELECT
  timestamp, equipment_id, oa_t,
  CASE
    WHEN oa_t IS NULL THEN false
    WHEN abs(oa_t - lag(oa_t) OVER (ORDER BY timestamp)) > 16.0 THEN true
    ELSE false
  END AS fault_raw
FROM telemetry_pivot
WHERE equipment_id = 'equip:weather'
```


## Trim & respond advisory

### TRIM-1 — Duct static trim advisory
**Family:** `trim` · **Equipment:** `ahu`  
**Equation:** Duct static high (> 1.35 in.w.c.) while VAV pressure requests are low.  
**Default confirmation:** 1800 s

| Param | Label | Unit | Default | Range |
|-------|-------|------|--------:|-------|
| `duct_hi` | Duct static high | in. w.c. | 1.35 | 0.5–3.0 |
| `request_lo` | Request sum low | count | 1.0 | 0.0–10.0 |

```sql
-- confirmation_seconds: 1800
-- Advisory: duct static SP high while requests low (trim candidate)
SELECT
  timestamp, equipment_id, duct_static_sp, static_reset_request,
  CASE
    WHEN duct_static_sp IS NULL THEN false
    WHEN duct_static_sp > 1.2 AND COALESCE(static_reset_request, 0) <= 0 THEN true
    ELSE false
  END AS fault_raw
FROM telemetry_pivot
WHERE equipment_id = 'equip:your-ahu'
```

### TRIM-3 — HWST trim advisory
**Family:** `trim` · **Equipment:** `boiler`  
**Equation:** HW supply > 160°F while reset requests are low.  
**Default confirmation:** 1800 s

| Param | Label | Unit | Default | Range |
|-------|-------|------|--------:|-------|
| `hwst_hi` | HWST high | °F | 160.0 | 120.0–200.0 |
| `request_lo` | Request sum low | count | 1.0 | 0.0–10.0 |

```sql
-- confirmation_seconds: 1800
-- rule: TRIM-3 — HWST trim advisory
-- equation: HW supply > 160°F while reset requests are low.

SELECT
  timestamp,
  equipment_id,
  hot_water_supply_temp,
  hw_reset_request_sum,
  CASE
    -- Implement TRIM-3 against assigned Haystack → FDD columns
    -- NULL samples must not latch faults
    WHEN false THEN false  -- stub: never latch until equation is coded
    ELSE false
  END AS fault_raw
FROM telemetry_pivot
WHERE equipment_id = 'equip:your-id'
```

### TRIM-4 — CHW plant reset advisory
**Family:** `trim` · **Equipment:** `chiller`  
**Equation:** CHW supply < 45°F while reset requests are low.  
**Default confirmation:** 1800 s

| Param | Label | Unit | Default | Range |
|-------|-------|------|--------:|-------|
| `chw_lo` | CHWS low | °F | 45.0 | 35.0–55.0 |
| `request_lo` | Request sum low | count | 1.0 | 0.0–10.0 |

```sql
-- confirmation_seconds: 1800
-- rule: TRIM-4 — CHW plant reset advisory
-- equation: CHW supply < 45°F while reset requests are low.

SELECT
  timestamp,
  equipment_id,
  chilled_water_supply_temp,
  chw_reset_request_sum,
  CASE
    -- Implement TRIM-4 against assigned Haystack → FDD columns
    -- NULL samples must not latch faults
    WHEN false THEN false  -- stub: never latch until equation is coded
    ELSE false
  END AS fault_raw
FROM telemetry_pivot
WHERE equipment_id = 'equip:your-id'
```

## Schedule & occupancy

### SCHED-1 — Unoccupied runtime
**Family:** `schedule` · **Equipment:** `ahu`  
**Equation:** Fan running while occupancy is unoccupied (Overview calendar → occ_mode). When zone_t is mapped, also require zone inside comfort_low_f…comfort_high_f (defaults 70–75°F; synced from Overview zone band).  
**Default confirmation:** 1800 s

| Param | Label | Unit | Default | Range |
|-------|-------|------|--------:|-------|
| `comfort_low_f` | Comfort low | °F | 70.0 | 60.0–78.0 |
| `comfort_high_f` | Comfort high | °F | 75.0 | 68.0–85.0 |

```sql
-- confirmation_seconds: 1800
SELECT
  timestamp, equipment_id, occ_mode, fan_status,
  CASE
    WHEN occ_mode IS NULL OR fan_status IS NULL THEN false
    WHEN lower(occ_mode) = 'unoccupied' AND fan_status THEN true
    ELSE false
  END AS fault_raw
FROM telemetry_pivot
WHERE equipment_id = 'equip:your-ahu'
```

### SCHED-247 — Always-on fan or pump runtime
**Family:** `schedule` · **Equipment:** `ahu`, `vav`, `chiller`, `boiler`, `heatpump`  
**Equation:** Fan or pump (or similar motor proof/command) is on for ≥ always_on_pct of the analysis window — highlights equipment that appears to run 24/7. Applies to all fans and pumps regardless of equipment family when a status/cmd role is mapped.  
**Default confirmation:** 3600 s

| Param | Label | Unit | Default | Range |
|-------|-------|------|--------:|-------|
| `always_on_pct` | Always-on fraction | frac | 0.95 | 0.8–1.0 |
| `pressure_on_min` | Pressure-on evidence | eng | 0.2 | 0.05–2.0 |

```sql
-- confirmation_seconds: 3600
-- Always-on screen: fan/pump command stays ON across the evaluation window
SELECT
  timestamp, equipment_id, fan_cmd,
  CASE
    WHEN fan_cmd IS NULL THEN false
    WHEN (CASE WHEN fan_cmd > 1.0 THEN fan_cmd / 100.0 ELSE fan_cmd END) >= 0.05 THEN true
    ELSE false
  END AS fault_raw
FROM telemetry_pivot
WHERE equipment_id = 'equip:your-ahu'
```

## Not yet in validated catalog

{: .important }
Documented for continuity — **not** in the current validated vibe19 catalog.

| ID | Title | Family |
|----|-------|--------|
| `VAV-2` | Night setback miss | `vav` |
| `VAV-6` | Reheat when cooling available | `vav` |
| `TOWER-1` | Cooling tower approach high | `plant` |
| `CTRL-2` | Generic control loop hunting | `control` |
| `RESET-1` | SAT reset not tracking outdoor air | `ahu` |
| `OVR-1` | Persistent override | `ahu` |
| `OA-2` | DCV minimum OA not met | `ahu` |
| `PLANT-1` | CHW DP reset missing | `plant` |
| `SP-HIGH` | Occupied setpoint too high | `vav` |
| `SP-LOW` | Occupied setpoint too low | `vav` |
| `KPI-1` | Performance score (advisory) | `site` |
| `TRIM-2` | Chiller plant enable advisory | `trim` |
| `WX-2` | Gust lower than sustained wind | `weather` |

---

## Framework & parity docs

- [Rule Cookbook hub](index.html)
- [Pandas cookbook](pandas-cookbook.html)
- [P0 rule catalog](p0-rule-catalog.html)
- [Parity matrix](parity-matrix.html)
- [Gap matrix](gap-matrix.html)
- [Prerequisite macros](prerequisite-macros.html)
