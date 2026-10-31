---
title: PostgreSQL SQL cookbook
parent: Rule Cookbook
nav_order: 2
---

# PostgreSQL / Timescale SQL FDD Cookbook

> **Engine (Wave-X 3.6+ / [ADR-010](../../architecture/adr-010-timescale-hard-cutover.md)):** Production FDD runs as **Timescale / PostgreSQL SQL** (`sql/fdd`). Soft-OPEN ≠ FQ. This page preserves the SQL expressions and engineering notes; it documents PostgreSQL execution, not a separate engine.

Open-FDD executes production fault detection through the versioned PostgreSQL registry [`sql/fdd/registry.yaml`](../../../sql/fdd/registry.yaml) on Timescale (**77** entries). Operator path: React **Run Rules** → `POST /api/fdd/run` (`mode=registry`). Raw arbitrary SQL is rejected.

**Pandas mirror:** the [Pandas cookbook](pandas-cookbook.html) documents the **71**-rule PyPI oracle (`open_fdd.rules`). Do **not** treat “71” as the production registry size. FCU / `zone_other`: [FCU and zone_other rules](fcu-zone-other.html).

The sketches under each rule explain the check. The SQL the product runs is in [Shipped SQL files](#shipped-sql-files).

**Unit contract:** Inputs and thresholds use SI processing units. Source values are normalized once by the telemetry writer from engineer-declared point units. Display preference is presentation-only. See [Unit contract](../../modeling/units.md).

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
9. [Fan coil / zone_other](#fan-coil--zone_other)
10. [Central plant / condenser water](#central-plant--condenser-water)
11. [Heat pumps](#heat-pumps)
12. [Weather station](#weather-station)
13. [Trim & respond advisory](#trim--respond-advisory)
14. [Schedule & occupancy](#schedule--occupancy)
15. [Not yet in validated catalog](#not-yet-in-validated-catalog)
16. [Framework & parity docs](#framework--parity-docs)
17. [Shipped SQL files](#shipped-sql-files)

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
    WHEN oa_t < -51.111111 OR oa_t > 54.444444 THEN true
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

**Sweep catalog (SV-RANGE / SV-FLATLINE / SV-STALE):** shipped SQL windows the pandas `SENSOR_LIMITS` roles on the wide `history` pivot — air/water temps (`oa_t`, `mat`, `zone_t`, `rat`, `sat`, `chw_supply_t`, `chw_return_t`, `hw_supply_t`, `hw_return_t`), humidity (`oa_h`, `ra_h`, `zone_rh`, `ma_h`, `sa_h` at 0–100 %RH with `RANGE_SCALE_HUMIDITY` / `SPIKE_SCALE_HUMIDITY`), and `duct_static` (−249–1991 Pa, `RANGE_SCALE_PRESSURE`). Temperature limits are per-role (for example SAT −1.11–65.56°C, zone/RA 4.44–37.78°C) with `RANGE_SCALE_TEMPERATURE`. **SV-FLATLINE** and **SV-STALE** use the flatline/stale subset (no `duct_static`). Status, command, setpoint, and mode columns are energization inputs only — not flatline/stale/range targets. Before scoring, SQL masks each sweep column with `fdd.mask_sweep_val(role, authorized_series.unit, value)` so a point with **no declared binding unit** is **not assessed** (same as pandas `sweep_assessable_role`).

### SV-RANGE — Sensor out of hard range
**Family:** `sensor` · **Equipment:** `ahu`, `vav`, `chiller`, `boiler`, `weather`, `zone`, `heatpump`  
**Equation:** Any modeled sensor reads outside its physical hard range (e.g. OAT −51.11–54.44°C, SAT −1.11–65.56°C, CHWS −1.11–26.67°C, RH 0–100 %).  
**Default confirmation:** 300 s

| Parameter | Kind | Label | SI unit | Default | Range |
|---|---|---|---|---:|---:|
| `minimum_active_coverage_pct` | `percent` | Min active coverage | % | 5.0 | 0.0–100.0 |
| `startup_delay_min` | `duration_minutes` | Startup delay | min | 0.0 | 0.0–60.0 |
| `require_operational_gate` | `boolean` | Require operational gate | boolean | 1.0 | 0.0–1.0 |
| `confirm_seconds` | `duration_seconds` | Confirm time | s | 300.0 | 0.0–3600.0 |
| `range_scale_temperature` | `dimensionless` | Temp range scale | × | 1.0 | 0.5–2.0 |
| `range_scale_humidity` | `dimensionless` | Humidity range scale | × | 1.0 | 0.5–2.0 |
| `range_scale_pressure` | `dimensionless` | Pressure / duct-static range scale | × | 1.0 | 0.5–2.0 |


```sql
-- confirmation_seconds: 300
-- Example hard-range screen for outdoor-air temperature (extend per sensor type)
SELECT
  timestamp, equipment_id, oa_t,
  CASE
    WHEN oa_t IS NULL THEN false
    WHEN oa_t < -51.111111 OR oa_t > 54.444444 THEN true
    ELSE false
  END AS fault_raw
FROM telemetry_pivot
```

### SV-FLATLINE — Sensor flatline (stuck)
**Family:** `sensor` · **Equipment:** `ahu`, `vav`, `chiller`, `boiler`, `weather`, `zone`, `heatpump`  
**Equation:** Sensor value unchanged (Δ ≤ tolerance) across the flatline window — stuck / frozen sensor.  
**Default confirmation:** 300 s

| Parameter | Kind | Label | SI unit | Default | Range |
|---|---|---|---|---:|---:|
| `minimum_active_coverage_pct` | `percent` | Min active coverage | % | 5.0 | 0.0–100.0 |
| `startup_delay_min` | `duration_minutes` | Startup delay | min | 0.0 | 0.0–60.0 |
| `require_operational_gate` | `boolean` | Require operational gate | boolean | 1.0 | 0.0–1.0 |
| `confirm_seconds` | `duration_seconds` | Confirm time | s | 300.0 | 0.0–3600.0 |
| `flatline_tol` | `temperature_difference` | Flatline tolerance | °C | 0.055556 | 0.011111–0.555556 |
| `flatline_hours` | `dimensionless` | Flatline window | h | 1.0 | 0.25–12.0 |



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

| Parameter | Kind | Label | SI unit | Default | Range |
|---|---|---|---|---:|---:|
| `minimum_active_coverage_pct` | `percent` | Min active coverage | % | 5.0 | 0.0–100.0 |
| `startup_delay_min` | `duration_minutes` | Startup delay | min | 0.0 | 0.0–60.0 |
| `require_operational_gate` | `boolean` | Require operational gate | boolean | 1.0 | 0.0–1.0 |
| `spike_scale_pressure` | `dimensionless` | Spike scale pressure | × | 1.0 | 0.25–4.0 |
| `spike_scale_humidity` | `dimensionless` | Spike scale humidity | × | 1.0 | 0.25–4.0 |
| `spike_scale_temperature` | `dimensionless` | Spike scale temperature | × | 1.0 | 0.25–4.0 |
| `confirm_seconds` | `duration_seconds` | Confirm time | s | 300.0 | 0.0–3600.0 |
| `spike_scale` | `dimensionless` | Spike limit scale (global) | × | 1.0 | 0.25–3.0 |



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

| Parameter | Kind | Label | SI unit | Default | Range |
|---|---|---|---|---:|---:|
| `confirm_seconds` | `duration_seconds` | Confirm time | s | 300.0 | 0.0–3600.0 |
| `stale_hours` | `dimensionless` | Stale window | h | 2.0 | 0.5–12.0 |
| `stale_tol` | `temperature_difference` | Stale tolerance | °C | 0.027778 | 0.0–0.555556 |


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

| Parameter | Kind | Label | SI unit | Default | Range |
|---|---|---|---|---:|---:|
| `sensor_span` | `dimensionless` | Sensor span | unit | 100.0 | 1.0–500.0 |
| `max_gap_hours` | `dimensionless` | Max sample gap | h | 1.0 | 0.1–12.0 |
| `confirm_seconds` | `duration_seconds` | Confirm time | s | 600.0 | 0.0–3600.0 |
| `persistence_min` | `duration_minutes` | Fault persistence | min | 10.0 | 5.0–60.0 |
| `steady_fault_per_hour` | `temperature_rate` | Steady-state slew limit | Δ°C/h | 3.333333333 | 0.555555556–33.333333333 |



{: .important }
**Contract status (metric-c-v2):** `SV-RATE` is `unsupported` in `sql/contract/metric_units.json` until its time policy is versioned. Pandas may implement screening logic; SQL remains a stub. Do not mark parity passing or flip availability without a versioned contract and green si-parity evidence.

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

| Parameter | Kind | Label | SI unit | Default | Range |
|---|---|---|---|---:|---:|
| `minimum_active_coverage_pct` | `percent` | Min active coverage | % | 5.0 | 0.0–100.0 |
| `startup_delay_min` | `duration_minutes` | Startup delay | min | 0.0 | 0.0–60.0 |
| `require_operational_gate` | `boolean` | Require operational gate | boolean | 1.0 | 0.0–1.0 |
| `confirm_seconds` | `duration_seconds` | Confirm time | s | 0.0 | 0.0–3600.0 |
| `window_hours` | `dimensionless` | Hunting lookback window | h | 1.0 | 0.25–4.0 |
| `change_deadband_pct` | `percent` | Ignore changes below | % | 1.0 | 0.0–10.0 |
| `minimum_span_pct` | `percent` | Minimum observed span | % | 20.0 | 5.0–100.0 |
| `total_variation_fault_pct` | `percent` | Total variation fault threshold | % | 500.0 | 50.0–2000.0 |
| `minimum_equivalent_cycles` | `count` | Min equivalent cycles | count | 2.5 | 0.5–10.0 |
| `minimum_reversals` | `count` | Min direction reversals | count | 4.0 | 1.0–20.0 |
| `minimum_coverage_pct` | `percent` | Min window sample coverage | % | 80.0 | 50.0–100.0 |



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

| Parameter | Kind | Label | SI unit | Default | Range |
|---|---|---|---|---:|---:|
| `minimum_active_coverage_pct` | `percent` | Min active coverage | % | 5.0 | 0.0–100.0 |
| `startup_delay_min` | `duration_minutes` | Startup delay | min | 0.0 | 0.0–60.0 |
| `require_operational_gate` | `boolean` | Require operational gate | boolean | 1.0 | 0.0–1.0 |
| `fan_on_min` | `fraction` | Fan-on command min | frac | 0.01 | 0.0–1.0 |
| `mode_delay_min` | `duration_minutes` | Mode delay after fan-on | min | 10.0 | 0.0–60.0 |
| `eps_dsp` | `air_pressure` | Duct-static error epsDSP (default 0.12 in. w.c.) | Pa | 29.8608 | 0.0–124.42 |
| `eps_vfd_spd` | `fraction` | VFD speed error epsVFDSPD (GL36 default 5%) | frac | 0.13 | 0.0–0.5 |
| `confirm_seconds` | `duration_seconds` | Confirm time | s | 300 | 0–3600 |


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

| Parameter | Kind | Label | SI unit | Default | Range |
|---|---|---|---|---:|---:|
| `minimum_active_coverage_pct` | `percent` | Min active coverage | % | 5.0 | 0.0–100.0 |
| `startup_delay_min` | `duration_minutes` | Startup delay | min | 0.0 | 0.0–60.0 |
| `require_operational_gate` | `boolean` | Require operational gate | boolean | 1.0 | 0.0–1.0 |
| `mode_delay_min` | `duration_minutes` | Mode delay after fan-on | min | 10.0 | 0.0–60.0 |
| `fan_on_min` | `fraction` | Fan-on command min | frac | 0.01 | 0.0–1.0 |
| `eps_rat` | `temperature_difference` | RAT sensor eps | °C | 0.638888889 | 0.0–5.555555556 |
| `eps_oat` | `temperature_difference` | OAT sensor eps | °C | 0.638888889 | 0.0–5.555555556 |
| `eps_mat` | `temperature_difference` | MAT sensor eps | °C | 0.638888889 | 0.0–5.555555556 |
| `mix_tol` | `temperature_difference` | Legacy master sensor tolerance (sets all eps values) | °C | 0.638888889 | 0.0–5.555555556 |
| `confirm_seconds` | `duration_seconds` | Confirm time | s | 600 | 0–3600 |


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

| Parameter | Kind | Label | SI unit | Default | Range |
|---|---|---|---|---:|---:|
| `minimum_active_coverage_pct` | `percent` | Min active coverage | % | 5.0 | 0.0–100.0 |
| `startup_delay_min` | `duration_minutes` | Startup delay | min | 0.0 | 0.0–60.0 |
| `require_operational_gate` | `boolean` | Require operational gate | boolean | 1.0 | 0.0–1.0 |
| `mode_delay_min` | `duration_minutes` | Mode delay after fan-on | min | 10.0 | 0.0–60.0 |
| `eps_rat` | `temperature_difference` | RAT sensor eps | °C | 0.638888889 | 0.0–5.555555556 |
| `eps_oat` | `temperature_difference` | OAT sensor eps | °C | 0.638888889 | 0.0–5.555555556 |
| `eps_mat` | `temperature_difference` | MAT sensor eps | °C | 0.638888889 | 0.0–5.555555556 |
| `mix_tol` | `temperature_difference` | Legacy master sensor tolerance (sets all eps values) | °C | 0.638888889 | 0.0–5.555555556 |
| `fan_on_min` | `fraction` | Fan ON fraction threshold | frac | 0.01 | 0.0–0.5 |
| `confirm_seconds` | `duration_seconds` | Confirm time | s | 600 | 0–3600 |


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

| Parameter | Kind | Label | SI unit | Default | Range |
|---|---|---|---|---:|---:|
| `minimum_active_coverage_pct` | `percent` | Min active coverage | % | 5.0 | 0.0–100.0 |
| `startup_delay_min` | `duration_minutes` | Startup delay | min | 0.0 | 0.0–60.0 |
| `require_operational_gate` | `boolean` | Require operational gate | boolean | 1.0 | 0.0–1.0 |
| `fan_on_min` | `fraction` | Fan-on command min | frac | 0.01 | 0.0–1.0 |
| `mode_delay_min` | `duration_minutes` | Mode delay after fan-on | min | 10.0 | 0.0–60.0 |
| `confirm_seconds` | `duration_seconds` | Confirm time | s | 3600.0 | 0.0–3600.0 |
| `delta_os_max` | `count` | Max operating-state entries per hour | count | 5.0 | 1.0–30.0 |



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

| Parameter | Kind | Label | SI unit | Default | Range |
|---|---|---|---|---:|---:|
| `minimum_active_coverage_pct` | `percent` | Min active coverage | % | 5.0 | 0.0–100.0 |
| `startup_delay_min` | `duration_minutes` | Startup delay | min | 0.0 | 0.0–60.0 |
| `require_operational_gate` | `boolean` | Require operational gate | boolean | 1.0 | 0.0–1.0 |
| `mode_delay_min` | `duration_minutes` | Mode delay after fan-on | min | 10.0 | 0.0–60.0 |
| `fan_on_min` | `fraction` | Fan-on command min | frac | 0.01 | 0.0–1.0 |
| `eps_sat` | `temperature_difference` | SAT sensor eps | °C | 0.638888889 | 0.0–5.555555556 |
| `eps_mat` | `temperature_difference` | MAT sensor eps | °C | 0.638888889 | 0.0–5.555555556 |
| `confirm_seconds` | `duration_seconds` | Confirm time | s | 600.0 | 0.0–3600.0 |
| `mix_tol` | `temperature_difference` | Legacy master sensor tolerance (sets all eps values) | °C | 0.638888889 | 0.0–5.555555556 |
| `htg_on_min` | `fraction` | Heating-command ON threshold | frac | 0.01 | 0.0–0.25 |
| `delta_supply_fan` | `temperature_difference` | Supply-fan delta (GL36 0.31Δ°C) | °C | 0.305555556 | 0.0–2.777777778 |


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

| Parameter | Kind | Label | SI unit | Default | Range |
|---|---|---|---|---:|---:|
| `minimum_active_coverage_pct` | `percent` | Min active coverage | % | 5.0 | 0.0–100.0 |
| `startup_delay_min` | `duration_minutes` | Startup delay | min | 0.0 | 0.0–60.0 |
| `require_operational_gate` | `boolean` | Require operational gate | boolean | 1.0 | 0.0–1.0 |
| `oat_rat_delta_min` | `temperature_difference` | Min |OAT-RAT| | °C | 2.777777778 | 0.0–16.666666667 |
| `mode_delay_min` | `duration_minutes` | Mode delay after fan-on | min | 10.0 | 0.0–60.0 |
| `fan_on_min` | `fraction` | Fan-on command min | frac | 0.01 | 0.0–1.0 |
| `eps_airflow` | `fraction` | Airflow fraction eps | frac | 0.15 | 0.05–1.0 |
| `confirm_seconds` | `duration_seconds` | Confirm time | s | 600.0 | 0.0–3600.0 |
| `min_L/s_design` | `volumetric_flow` | Design minimum outdoor airflow | L/s | 2359.735 | 0.0–94389.4 |


```sql
-- confirmation_seconds: 600
-- rule: FC6 — Estimated OA fraction mismatch
-- equation: |RAT−OAT| ≥ 2.777778Δ°C AND |estimated OA% − design min OA%| > 15% in heating/mech-only modes.

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

| Parameter | Kind | Label | SI unit | Default | Range |
|---|---|---|---|---:|---:|
| `minimum_active_coverage_pct` | `percent` | Min active coverage | % | 5.0 | 0.0–100.0 |
| `startup_delay_min` | `duration_minutes` | Startup delay | min | 0.0 | 0.0–60.0 |
| `require_operational_gate` | `boolean` | Require operational gate | boolean | 1.0 | 0.0–1.0 |
| `mode_delay_min` | `duration_minutes` | Mode delay after fan-on | min | 10.0 | 0.0–60.0 |
| `fan_on_min` | `fraction` | Fan-on command min | frac | 0.01 | 0.0–1.0 |
| `eps_sat` | `temperature_difference` | SAT sensor eps | °C | 0.638888889 | 0.0–5.555555556 |
| `htg_full_min` | `fraction` | Full-heating threshold (GL36 99%) | frac | 0.9 | 0.5–1.0 |
| `confirm_seconds` | `duration_seconds` | Confirm time | s | 600 | 0–3600 |


```sql
-- htg_valve_pct >= HTG_FULL_MIN; fan_status then fan_cmd. sql/fdd/postgres/rules/fc7_sat_low_heating.sql
SELECT equipment_id, fault_hours FROM fc7_sat_low_heating_result
```

### FC8 — SAT/MAT mismatch in economizer (GL36 F)
**Family:** `ahu` · **Equipment:** `ahu`  
**Equation:** |SATavg − ΔTSF − MATavg| > √(εSAT² + εMAT²) in OS#2.  
**Default confirmation:** 600 s

| Parameter | Kind | Label | SI unit | Default | Range |
|---|---|---|---|---:|---:|
| `minimum_active_coverage_pct` | `percent` | Min active coverage | % | 5.0 | 0.0–100.0 |
| `startup_delay_min` | `duration_minutes` | Startup delay | min | 0.0 | 0.0–60.0 |
| `require_operational_gate` | `boolean` | Require operational gate | boolean | 1.0 | 0.0–1.0 |
| `fan_on_min` | `fraction` | Fan-on command min | frac | 0.01 | 0.0–1.0 |
| `mode_delay_min` | `duration_minutes` | Mode delay after fan-on | min | 10.0 | 0.0–60.0 |
| `supply_tol` | `temperature_difference` | Supply tol (alias eps_sat) | °C | 0.638888889 | 0.0–5.555555556 |
| `eps_sat` | `temperature_difference` | SAT sensor eps | °C | 0.638888889 | 0.0–5.555555556 |
| `eps_mat` | `temperature_difference` | MAT sensor eps | °C | 0.638888889 | 0.0–5.555555556 |
| `mix_tol` | `temperature_difference` | Legacy master sensor tolerance (sets all eps values) | °C | 0.638888889 | 0.0–5.555555556 |
| `delta_supply_fan` | `temperature_difference` | Supply-fan delta (GL36 0.31Δ°C) | °C | 0.305555556 | 0.0–2.777777778 |
| `econ_min_pos` | `fraction` | Economizer OA damper minimum (fraction) | frac | 0.05 | 0.0–0.5 |
| `clg_inactive_max` | `fraction` | Cooling valve inactive max (fraction) | frac | 0.1 | 0.0–0.5 |
| `confirm_seconds` | `duration_seconds` | Confirm time | s | 600 | 0–3600 |


```sql
-- confirmation_seconds: 600
-- rule: FC8 — SAT/MAT mismatch in economizer (GL36 F)
-- equation: Economizer open, CHW < 10%, |SAT − 0.305556Δ°C − MAT| > √(supply_tol²+mix_tol²).

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

| Parameter | Kind | Label | SI unit | Default | Range |
|---|---|---|---|---:|---:|
| `minimum_active_coverage_pct` | `percent` | Min active coverage | % | 5.0 | 0.0–100.0 |
| `startup_delay_min` | `duration_minutes` | Startup delay | min | 0.0 | 0.0–60.0 |
| `require_operational_gate` | `boolean` | Require operational gate | boolean | 1.0 | 0.0–1.0 |
| `fan_on_min` | `fraction` | Fan-on command min | frac | 0.01 | 0.0–1.0 |
| `mode_delay_min` | `duration_minutes` | Mode delay after fan-on | min | 10.0 | 0.0–60.0 |
| `eps_sat` | `temperature_difference` | SAT sensor eps | °C | 0.638888889 | 0.0–5.555555556 |
| `eps_oat` | `temperature_difference` | OAT sensor eps | °C | 0.638888889 | 0.0–5.555555556 |
| `mix_tol` | `temperature_difference` | Legacy master sensor tolerance (sets all eps values) | °C | 0.638888889 | 0.0–5.555555556 |
| `delta_supply_fan` | `temperature_difference` | Supply-fan delta (GL36 0.31Δ°C) | °C | 0.305555556 | 0.0–2.777777778 |
| `econ_min_pos` | `fraction` | Economizer OA damper minimum (fraction) | frac | 0.05 | 0.0–0.5 |
| `clg_inactive_max` | `fraction` | Cooling valve inactive max (fraction) | frac | 0.1 | 0.0–0.5 |
| `confirm_seconds` | `duration_seconds` | Confirm time | s | 600 | 0–3600 |


```sql
-- confirmation_seconds: 600
-- rule: FC9 — OAT too warm for free cooling (GL36 G)
-- equation: Economizer open, CHW < 10%, OAT − mix_tol > SAT SP − 0.305556Δ°C + mix_tol.

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

| Parameter | Kind | Label | SI unit | Default | Range |
|---|---|---|---|---:|---:|
| `minimum_active_coverage_pct` | `percent` | Min active coverage | % | 5.0 | 0.0–100.0 |
| `startup_delay_min` | `duration_minutes` | Startup delay | min | 0.0 | 0.0–60.0 |
| `require_operational_gate` | `boolean` | Require operational gate | boolean | 1.0 | 0.0–1.0 |
| `fan_on_min` | `fraction` | Fan-on command min | frac | 0.01 | 0.0–1.0 |
| `mode_delay_min` | `duration_minutes` | Mode delay after fan-on | min | 10.0 | 0.0–60.0 |
| `eps_oat` | `temperature_difference` | OAT sensor eps | °C | 0.638888889 | 0.0–5.555555556 |
| `eps_mat` | `temperature_difference` | MAT sensor eps | °C | 0.638888889 | 0.0–5.555555556 |
| `econ_full_open` | `fraction` | Econ damper full-open | frac | 0.9 | 0.5–1.0 |
| `mix_tol` | `temperature_difference` | Legacy master sensor tolerance (sets all eps values) | °C | 0.638888889 | 0.0–5.555555556 |
| `clg_on_min` | `fraction` | Cooling valve ON minimum (fraction) | frac | 0.01 | 0.0–0.5 |
| `confirm_seconds` | `duration_seconds` | Confirm time | s | 600 | 0–3600 |


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

| Parameter | Kind | Label | SI unit | Default | Range |
|---|---|---|---|---:|---:|
| `minimum_active_coverage_pct` | `percent` | Min active coverage | % | 5.0 | 0.0–100.0 |
| `startup_delay_min` | `duration_minutes` | Startup delay | min | 0.0 | 0.0–60.0 |
| `require_operational_gate` | `boolean` | Require operational gate | boolean | 1.0 | 0.0–1.0 |
| `fan_on_min` | `fraction` | Fan-on command min | frac | 0.01 | 0.0–1.0 |
| `mode_delay_min` | `duration_minutes` | Mode delay after fan-on | min | 10.0 | 0.0–60.0 |
| `eps_sat` | `temperature_difference` | SAT sensor eps | °C | 0.638888889 | 0.0–5.555555556 |
| `eps_oat` | `temperature_difference` | OAT sensor eps | °C | 0.638888889 | 0.0–5.555555556 |
| `econ_full_open` | `fraction` | Econ damper full-open | frac | 0.9 | 0.5–1.0 |
| `mix_tol` | `temperature_difference` | Legacy master sensor tolerance (sets all eps values) | °C | 0.638888889 | 0.0–5.555555556 |
| `delta_supply_fan` | `temperature_difference` | Supply-fan delta (GL36 0.31Δ°C) | °C | 0.305555556 | 0.0–2.777777778 |
| `clg_on_min` | `fraction` | Cooling valve ON minimum (fraction) | frac | 0.01 | 0.0–0.5 |
| `confirm_seconds` | `duration_seconds` | Confirm time | s | 600 | 0–3600 |


```sql
-- confirmation_seconds: 600
-- rule: FC11 — OAT/MAT mismatch economizer-only (GL36 I)
-- equation: CHW > 1%, economizer > 90%, OAT + mix_tol < SAT SP − 0.305556Δ°C − mix_tol.

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

| Parameter | Kind | Label | SI unit | Default | Range |
|---|---|---|---|---:|---:|
| `minimum_active_coverage_pct` | `percent` | Min active coverage | % | 5.0 | 0.0–100.0 |
| `startup_delay_min` | `duration_minutes` | Startup delay | min | 0.0 | 0.0–60.0 |
| `require_operational_gate` | `boolean` | Require operational gate | boolean | 1.0 | 0.0–1.0 |
| `fan_on_min` | `fraction` | Fan-on command min | frac | 0.01 | 0.0–1.0 |
| `mode_delay_min` | `duration_minutes` | Mode delay after fan-on | min | 10.0 | 0.0–60.0 |
| `supply_tol` | `temperature_difference` | Supply tol (alias eps_sat) | °C | 0.638888889 | 0.0–5.555555556 |
| `eps_sat` | `temperature_difference` | SAT sensor eps | °C | 0.638888889 | 0.0–5.555555556 |
| `eps_mat` | `temperature_difference` | MAT sensor eps | °C | 0.638888889 | 0.0–5.555555556 |
| `econ_full_open` | `fraction` | Econ damper full-open | frac | 0.9 | 0.5–1.0 |
| `mix_tol` | `temperature_difference` | Legacy master sensor tolerance (sets all eps values) | °C | 0.638888889 | 0.0–5.555555556 |
| `delta_supply_fan` | `temperature_difference` | Supply-fan delta (GL36 0.31Δ°C) | °C | 0.305555556 | 0.0–2.777777778 |
| `clg_on_min` | `fraction` | Cooling valve ON minimum (fraction) | frac | 0.01 | 0.0–0.5 |
| `econ_min_pos` | `fraction` | Economizer OA damper minimum (fraction) | frac | 0.05 | 0.0–0.5 |
| `confirm_seconds` | `duration_seconds` | Confirm time | s | 600 | 0–3600 |


```sql
-- confirmation_seconds: 600
-- rule: FC12 — SAT above blend in cooling (GL36 J)
-- equation: CHW > 1%, SAT − supply_tol − 0.305556Δ°C > MAT + mix_tol at min or full economizer.

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

| Parameter | Kind | Label | SI unit | Default | Range |
|---|---|---|---|---:|---:|
| `minimum_active_coverage_pct` | `percent` | Min active coverage | % | 5.0 | 0.0–100.0 |
| `startup_delay_min` | `duration_minutes` | Startup delay | min | 0.0 | 0.0–60.0 |
| `require_operational_gate` | `boolean` | Require operational gate | boolean | 1.0 | 0.0–1.0 |
| `fan_on_min` | `fraction` | Fan-on command min | frac | 0.01 | 0.0–1.0 |
| `mode_delay_min` | `duration_minutes` | Mode delay after fan-on | min | 10.0 | 0.0–60.0 |
| `eps_sat` | `temperature_difference` | SAT sensor eps | °C | 0.638888889 | 0.0–5.555555556 |
| `econ_min_pos` | `fraction` | Econ damper min pos | frac | 0.05 | 0.0–0.5 |
| `econ_full_open` | `fraction` | Econ damper full-open | frac | 0.9 | 0.5–1.0 |
| `clg_full_min` | `fraction` | Cooling valve full min | frac | 0.9 | 0.5–1.0 |
| `oa_damper_econ_low` | `fraction` | OA damper economizer low | frac | 0.05 | 0.0–0.5 |
| `confirm_seconds` | `duration_seconds` | Confirm time | s | 600 | 0–3600 |


```sql
-- confirmation_seconds: 600
-- rule: FC13 — SAT above SP at full cooling (GL36 K)
-- equation: CHW > 1%, SAT > SAT SP + 0.555556Δ°C at min or full economizer.

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

| Parameter | Kind | Label | SI unit | Default | Range |
|---|---|---|---|---:|---:|
| `clg_on_min` | `fraction` | Cooling on min | frac | 0.01 | 0.0–1.0 |
| `minimum_active_coverage_pct` | `percent` | Min active coverage | % | 5.0 | 0.0–100.0 |
| `startup_delay_min` | `duration_minutes` | Startup delay | min | 0.0 | 0.0–60.0 |
| `require_operational_gate` | `boolean` | Require operational gate | boolean | 1.0 | 0.0–1.0 |
| `fan_on_min` | `fraction` | Fan-on command min | frac | 0.01 | 0.0–1.0 |
| `mode_delay_min` | `duration_minutes` | Mode delay after fan-on | min | 10.0 | 0.0–60.0 |
| `htg_on_min` | `fraction` | Heating on min | frac | 0.01 | 0.0–1.0 |
| `eps_cclt` | `temperature_difference` | CHW coil leaving eps | °C | 0.638888889 | 0.0–5.555555556 |
| `eps_ccet` | `temperature_difference` | CHW coil entering eps | °C | 0.638888889 | 0.0–5.555555556 |
| `econ_min_pos` | `fraction` | Econ damper min pos | frac | 0.05 | 0.0–0.5 |
| `delta_supply_fan` | `temperature_difference` | Supply-fan delta | °C | 0.305555556 | 0.0–2.777777778 |
| `clg_inactive_max` | `fraction` | Cooling inactive max | frac | 0.01 | 0.0–0.5 |
| `confirm_seconds` | `duration_seconds` | Confirm time | s | 600.0 | 0.0–3600.0 |
| `mix_tol` | `temperature_difference` | Legacy master sensor tolerance (sets all eps values) | °C | 0.638888889 | 0.0–5.555555556 |


```sql
-- confirmation_seconds: 600
-- rule: FC14 — CHW coil ΔT when inactive (GL36 L)
-- equation: Cooling coil ΔT ≥ √(mix_tol²+mix_tol²)+0.305556Δ°C while coil should be inactive.

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

| Parameter | Kind | Label | SI unit | Default | Range |
|---|---|---|---|---:|---:|
| `htg_on_min` | `fraction` | Heating on min | frac | 0.01 | 0.0–1.0 |
| `minimum_active_coverage_pct` | `percent` | Min active coverage | % | 5.0 | 0.0–100.0 |
| `startup_delay_min` | `duration_minutes` | Startup delay | min | 0.0 | 0.0–60.0 |
| `require_operational_gate` | `boolean` | Require operational gate | boolean | 1.0 | 0.0–1.0 |
| `fan_on_min` | `fraction` | Fan-on command min | frac | 0.01 | 0.0–1.0 |
| `mode_delay_min` | `duration_minutes` | Mode delay after fan-on | min | 10.0 | 0.0–60.0 |
| `eps_hclt` | `temperature_difference` | HW coil leaving eps | °C | 0.638888889 | 0.0–5.555555556 |
| `eps_hcet` | `temperature_difference` | HW coil entering eps | °C | 0.638888889 | 0.0–5.555555556 |
| `econ_min_pos` | `fraction` | Econ damper min pos | frac | 0.05 | 0.0–0.5 |
| `econ_full_open` | `fraction` | Econ damper full-open | frac | 0.9 | 0.5–1.0 |
| `delta_supply_fan` | `temperature_difference` | Supply-fan delta | °C | 0.305555556 | 0.0–2.777777778 |
| `clg_on_min` | `fraction` | Cooling on min | frac | 0.01 | 0.0–1.0 |
| `clg_inactive_max` | `fraction` | Cooling inactive max | frac | 0.01 | 0.0–0.5 |
| `confirm_seconds` | `duration_seconds` | Confirm time | s | 600.0 | 0.0–3600.0 |
| `mix_tol` | `temperature_difference` | Legacy master sensor tolerance (sets all eps values) | °C | 0.638888889 | 0.0–5.555555556 |


```sql
-- confirmation_seconds: 600
-- rule: FC15 — HW coil ΔT when inactive (GL36 M)
-- equation: Heating coil ΔT ≥ √(mix_tol²+mix_tol²)+0.305556Δ°C while coil should be inactive.

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
**Equation:** |SAT − SAT SP| > 2.78Δ°C.  
**Default confirmation:** 600 s

| Parameter | Kind | Label | SI unit | Default | Range |
|---|---|---|---|---:|---:|
| `minimum_active_coverage_pct` | `percent` | Min active coverage | % | 5.0 | 0.0–100.0 |
| `startup_delay_min` | `duration_minutes` | Startup delay | min | 0.0 | 0.0–60.0 |
| `require_operational_gate` | `boolean` | Require operational gate | boolean | 1.0 | 0.0–1.0 |
| `confirm_seconds` | `duration_seconds` | Confirm time | s | 600.0 | 0.0–3600.0 |
| `sat_dev_err` | `temperature_difference` | SAT deviation | Δ°C | 2.777778 | 0.555556–8.333333 |


```sql
-- confirmation_seconds: 600
-- rule: AHU-SATDEV — SAT deviation from setpoint
-- equation: |SAT − SAT SP| > 2.777778Δ°C.

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

| Parameter | Kind | Label | SI unit | Default | Range |
|---|---|---|---|---:|---:|
| `minimum_active_coverage_pct` | `percent` | Min active coverage | % | 5.0 | 0.0–100.0 |
| `startup_delay_min` | `duration_minutes` | Startup delay | min | 0.0 | 0.0–60.0 |
| `require_operational_gate` | `boolean` | Require operational gate | boolean | 1.0 | 0.0–1.0 |
| `confirm_seconds` | `duration_seconds` | Confirm time | s | 300.0 | 0.0–3600.0 |
| `duct_high_margin` | `air_pressure` | High margin | Pa | 62.21 | 12.442–248.84 |
| `pressure_on_min` | `air_pressure` | Pressure-on evidence | Pa | 49.768 | 12.442–248.84 |


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

| Parameter | Kind | Label | SI unit | Default | Range |
|---|---|---|---|---:|---:|
| `minimum_active_coverage_pct` | `percent` | Min active coverage | % | 5.0 | 0.0–100.0 |
| `startup_delay_min` | `duration_minutes` | Startup delay | min | 0.0 | 0.0–60.0 |
| `require_operational_gate` | `boolean` | Require operational gate | boolean | 1.0 | 0.0–1.0 |
| `confirm_seconds` | `duration_seconds` | Confirm time | s | 300.0 | 0.0–3600.0 |
| `valve_open_pct` | `fraction` | Valve open threshold | frac | 0.1 | 0.05–0.5 |


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
**Equation:** BAS outdoor-air sensor differs from Open-Meteo dry bulb by more than 2.78Δ°C after an as-of web alignment.  
The shipped rule (`sql/fdd/postgres/rules/oat_meteo_fault.sql`) does not filter `equipment_id`. Applicability is registry `equipment_kinds: [ahu]` plus the package stamp, so `AC_1` stamped `ahu` is in scope and an id that starts with `AHU` but is stamped `vav` is not.  
**Default confirmation:** 900 s

| Parameter | Kind | Label | SI unit | Default | Range |
|---|---|---|---|---:|---:|
| `oat_err` | `temperature_difference` | OAT vs meteo tolerance | °C | 2.777778 | 1.111111–11.111111 |
| `confirm_seconds` | `duration_seconds` | Confirm time | s | 900 | 0–3600 |
| `web_cadence_seconds` | `duration_seconds` | Web weather cadence | s | 1200 | 300–7200 |
| `web_asof_margin_seconds` | `duration_seconds` | Web as-of margin | s | 300 | 0–1800 |


Web OAT (`web_oa_t` on equipment or weather rows) is joined **as-of** each local BAS timestamp: carry the last web sample forward. Samples whose last web value is older than `web_cadence_seconds + web_asof_margin_seconds` are **not assessed** (not fault time). Local `oa_t` uses the point marked `primary_reference` for the role when set; see [`provider-point-overlay.md`](../../modeling/provider-point-overlay.html).

```sql
-- confirmation_seconds: 900
-- param: oat_err = 5.0
-- param: web_cadence_seconds = 1200, web_asof_margin_seconds = 300
-- assessable=false → not assessed; assessable=true and |oa_t - ref| > oat_err → fault_raw
SELECT
  timestamp, equipment_id, oa_t, ref_oa_t, assessable,
  CASE
    WHEN NOT assessable THEN NULL
    WHEN abs(oa_t - ref_oa_t) > 5.0 THEN true
    ELSE false
  END AS fault_raw
FROM joined
WHERE equipment_id = 'equip:your-ahu'
```


### ECON-1 — Economizer stuck closed
**Family:** `ahu` · **Equipment:** `ahu`  
**Equation:** Fan on, OA damper < 5%, OAT > 12.78°C (should be economizing).  
**Default confirmation:** 600 s

| Parameter | Kind | Label | SI unit | Default | Range |
|---|---|---|---|---:|---:|
| `minimum_active_coverage_pct` | `percent` | Min active coverage | % | 5.0 | 0.0–100.0 |
| `startup_delay_min` | `duration_minutes` | Startup delay | min | 0.0 | 0.0–60.0 |
| `require_operational_gate` | `boolean` | Require operational gate | boolean | 1.0 | 0.0–1.0 |
| `econ1_oat_min` | `absolute_temperature` | Favorable OAT | °C | 12.777778 | 7.222222–21.111111 |
| `econ1_damper_max` | `fraction` | Stuck-closed damper frac | frac | 0.05 | 0.0–0.2 |


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
**Equation:** OAT > 17.22°C AND OA damper > 42% (should be at minimum).  
**Default confirmation:** 300 s

| Parameter | Kind | Label | SI unit | Default | Range |
|---|---|---|---|---:|---:|
| `minimum_active_coverage_pct` | `percent` | Min active coverage | % | 5.0 | 0.0–100.0 |
| `startup_delay_min` | `duration_minutes` | Startup delay | min | 0.0 | 0.0–60.0 |
| `require_operational_gate` | `boolean` | Require operational gate | boolean | 1.0 | 0.0–1.0 |
| `econ2_oat_hi` | `absolute_temperature` | OAT high cutoff | °C | 17.222222 | 12.777778–26.666667 |
| `econ2_damper` | `fraction` | Damper open frac | frac | 0.42 | 0.2–0.9 |
| `confirm_seconds` | `duration_seconds` | Confirm time | s | 300 | 0–3600 |


```sql
-- confirmation_seconds: 300
-- rule: ECON-2 — Economizing when outdoor unfavorable
-- equation: OAT > 17.222222°C AND OA damper > 42% (should be at minimum).

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
**Equation:** Web free-cooling opportunity (15.56°C ≤ DB < 22.22°C AND dewpoint < 15.56°C) while cooling valve open and OA damper below integrated threshold (default 90%).  
**Default confirmation:** 300 s

| Parameter | Kind | Label | SI unit | Default | Range |
|---|---|---|---|---:|---:|
| `minimum_active_coverage_pct` | `percent` | Min active coverage | % | 5.0 | 0.0–100.0 |
| `startup_delay_min` | `duration_minutes` | Startup delay | min | 0.0 | 0.0–60.0 |
| `require_operational_gate` | `boolean` | Require operational gate | boolean | 1.0 | 0.0–1.0 |
| `confirm_seconds` | `duration_seconds` | Confirm time | s | 300.0 | 0.0–3600.0 |
| `econ3_db_min` | `absolute_temperature` | Free-cool OA dry-bulb min | °C | 15.555556 | 10.0–20.0 |
| `econ3_db_max` | `absolute_temperature` | Free-cool OA dry-bulb max | °C | 22.222222 | 18.333333–26.666667 |
| `econ3_dp_max` | `absolute_temperature` | Free-cool OA dew point max | °C | 15.555556 | 7.222222–20.0 |
| `econ3_damper_hi` | `fraction` | Integrated economizer damper | frac | 0.9 | 0.5–1.0 |
| `clg_open_min` | `fraction` | Cooling valve open minimum | frac | 0.01 | 0.0–0.5 |


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
**Equation:** Fan on, |RAT−OAT| > 1.22Δ°C, estimated OA fraction < 21%.  
**Default confirmation:** 600 s

| Parameter | Kind | Label | SI unit | Default | Range |
|---|---|---|---|---:|---:|
| `minimum_active_coverage_pct` | `percent` | Min active coverage | % | 5.0 | 0.0–100.0 |
| `startup_delay_min` | `duration_minutes` | Startup delay | min | 0.0 | 0.0–60.0 |
| `require_operational_gate` | `boolean` | Require operational gate | boolean | 1.0 | 0.0–1.0 |
| `oa_min_pct` | `percent` | Min OA fraction | % | 21.0 | 5.0–40.0 |
| `oat_rat_delta_min` | `temperature_difference` | Min |RAT−OAT| for OA-fraction estimate  | Δ°C | 1.222222 | 0.277778–5.555556 |
| `confirm_seconds` | `duration_seconds` | Confirm time | s | 600 | 0–3600 |


```sql
-- confirmation_seconds: 600
-- rule: ECON-4 — Low estimated OA fraction
-- equation: Fan on, |RAT−OAT| > 1.222222Δ°C, estimated OA fraction < 21%.

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
**Equation:** Preheat leaving air > 1.22Δ°C above target while preheat active.  
**Default confirmation:** 600 s

| Parameter | Kind | Label | SI unit | Default | Range |
|---|---|---|---|---:|---:|
| `minimum_active_coverage_pct` | `percent` | Min active coverage | % | 5.0 | 0.0–100.0 |
| `startup_delay_min` | `duration_minutes` | Startup delay | min | 0.0 | 0.0–60.0 |
| `require_operational_gate` | `boolean` | Require operational gate | boolean | 1.0 | 0.0–1.0 |
| `confirm_seconds` | `duration_seconds` | Confirm time | s | 600.0 | 0.0–3600.0 |
| `preheat_over` | `temperature_difference` | Preheat over ΔT | Δ°C | 1.222222 | 0.277778–4.444444 |
| `htg_open_min` | `fraction` | Heating valve open minimum | frac | 0.01 | 0.0–0.5 |


```sql
-- confirmation_seconds: 600
-- rule: ECON-5 — Preheat over-conditioning
-- equation: Preheat leaving air > 1.222222Δ°C above target while preheat active.

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
**Equation:** Web dry-bulb < -3.89°C AND OA damper above winter min-OA ceiling (default 25%). AHU should be at minimum OA in cold weather.  
**Default confirmation:** 600 s

| Parameter | Kind | Label | SI unit | Default | Range |
|---|---|---|---|---:|---:|
| `minimum_active_coverage_pct` | `percent` | Min active coverage | % | 5.0 | 0.0–100.0 |
| `startup_delay_min` | `duration_minutes` | Startup delay | min | 0.0 | 0.0–60.0 |
| `require_operational_gate` | `boolean` | Require operational gate | boolean | 1.0 | 0.0–1.0 |
| `confirm_seconds` | `duration_seconds` | Confirm time | s | 600.0 | 0.0–3600.0 |
| `econ6_oat_max` | `absolute_temperature` | Winter OAT ceiling | °C | -3.888889 | -9.444444–4.444444 |
| `econ6_damper_max` | `fraction` | Winter min-OA damper | frac | 0.25 | 0.05–0.5 |


```sql
-- confirmation_seconds: 600
-- rule: ECON-6 — Economizing in freezing weather
-- equation: Web dry-bulb < -3.888889°C AND OA damper above winter min-OA ceiling (default 25%). AHU should be at minimum OA in cold weather.

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
**Equation:** Economizer-OK web weather: dew point < 15.56°C AND dry-bulb < 22.22°C (above a 1.67°C freeze-guard floor; dewpoint from web sensor or calculated from web DB+RH). Fault when there is cooling demand (cooling valve open or proven DX/chiller cooling) but the OA damper stays below the economizing threshold (default 50%). Expected: economizer-only below 15.56°C DB (MECH-OAT-1) and mech + integrated economizer in the 15.56–22.22°C band (ECON-3). All thresholds are SI parameters.  
**Default confirmation:** 600 s

| Parameter | Kind | Label | SI unit | Default | Range |
|---|---|---|---|---:|---:|
| `minimum_active_coverage_pct` | `percent` | Min active coverage | % | 5.0 | 0.0–100.0 |
| `startup_delay_min` | `duration_minutes` | Startup delay | min | 0.0 | 0.0–60.0 |
| `require_operational_gate` | `boolean` | Require operational gate | boolean | 1.0 | 0.0–1.0 |
| `confirm_seconds` | `duration_seconds` | Confirm time | s | 600.0 | 0.0–3600.0 |
| `econ7_db_min` | `absolute_temperature` | Econ-OK dry-bulb floor (freeze guard) | °C | 1.666667 | -6.666667–10.0 |
| `econ7_db_max` | `absolute_temperature` | Econ-OK dry-bulb max | °C | 22.222222 | 18.333333–26.666667 |
| `econ7_dp_max` | `absolute_temperature` | Econ-OK dew point max | °C | 15.555556 | 7.222222–20.0 |
| `econ7_damper_min` | `fraction` | Economizing damper threshold | frac | 0.5 | 0.2–0.9 |
| `clg_open_min` | `fraction` | Cooling valve open minimum | frac | 0.05 | 0.0–0.5 |


```sql
-- confirmation_seconds: 600
-- rule: ECON-7 — Economizer OK but not economizing
-- equation: Economizer-OK web weather: dew point < 15.555556°C AND dry-bulb < 22.222222°C (above a 1.666667°C freeze-guard floor; dewpoint from web sensor or calculated from web DB+RH). Fault when there is cooling demand (cooling valve open or proven DX/chiller cooling) but the OA damper stays below the economizing threshold (default 50%). Expected: economizer-only below 15.555556°C DB (MECH-OAT-1) and mech + integrated economizer in the 15.555556–22.222222°C band (ECON-3). All thresholds are SI parameters.

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

### MECH-OAT-1 — Mechanical cooling below 15.56°C web OAT
**Family:** `ahu` · **Equipment:** `ahu`, `chiller`, `heatpump`  
**Equation:** Proven DX/chiller mechanical cooling while web dry-bulb < 15.56°C. Uses compressor/chiller/pump/amps/power proof — not AHU cooling-valve alone. Below 15.56°C is outside the free-cool + integrated economizer band.  
**Default confirmation:** 600 s

| Parameter | Kind | Label | SI unit | Default | Range |
|---|---|---|---|---:|---:|
| `confirm_seconds` | `duration_seconds` | Confirm time | s | 600.0 | 0.0–3600.0 |
| `mech_oat_max` | `absolute_temperature` | Mech-cool OAT ceiling | °C | 15.555556 | 7.222222–18.333333 |


```sql
-- confirmation_seconds: 600
-- rule: MECH-OAT-1 — Mechanical cooling below 15.555556°C web OAT
-- equation: Proven DX/chiller mechanical cooling while web dry-bulb < 15.555556°C. Uses compressor/chiller/pump/amps/power proof — not AHU cooling-valve alone. Below 15.555556°C is outside the free-cool + integrated economizer band.

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

### RESET-1 — SAT reset not tracking outdoor air
**Family:** `ahu` · **Equipment:** `ahu`  
**Equation:** Fan on AND |SAT SP − (11.111111 + 0.25×(OAT−18.333333))| > 1.67Δ°C.  
**Default confirmation:** 900 s

_No extra cookbook params beyond confirmation in this snippet; production SQL uses `sql/fdd/postgres/rules/reset1_sat_oa_reset.sql`._

```sql
-- confirmation_seconds: 900
-- See sql/fdd/postgres/rules/reset1_sat_oa_reset.sql
SELECT equipment_id, fault_hours FROM reset1_sat_oa_reset_result
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

| Parameter | Kind | Label | SI unit | Default | Range |
|---|---|---|---|---:|---:|
| `minimum_active_coverage_pct` | `percent` | Min active coverage | % | 5.0 | 0.0–100.0 |
| `startup_delay_min` | `duration_minutes` | Startup delay | min | 0.0 | 0.0–60.0 |
| `require_operational_gate` | `boolean` | Require operational gate | boolean | 1.0 | 0.0–1.0 |
| `confirm_seconds` | `duration_seconds` | Confirm time | s | 900.0 | 0.0–3600.0 |
| `min_oa_frac` | `fraction` | Min OA fraction | frac | 0.15 | 0.05–0.4 |
| `oat_rat_guard` | `temperature_difference` | OAT/RAT guard | Δ°C | 1.222222 | 0.277778–3.333333 |


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
**Equation:** Damper ≤ 5% but MAT tracks OAT within 1.11Δ°C — leaking OA damper.  
**Default confirmation:** 900 s

| Parameter | Kind | Label | SI unit | Default | Range |
|---|---|---|---|---:|---:|
| `minimum_active_coverage_pct` | `percent` | Min active coverage | % | 5.0 | 0.0–100.0 |
| `startup_delay_min` | `duration_minutes` | Startup delay | min | 0.0 | 0.0–60.0 |
| `require_operational_gate` | `boolean` | Require operational gate | boolean | 1.0 | 0.0–1.0 |
| `confirm_seconds` | `duration_seconds` | Confirm time | s | 900.0 | 0.0–3600.0 |
| `leak_delta` | `temperature_difference` | Leak ΔT | Δ°C | 1.111111 | 0.277778–3.333333 |


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

| Parameter | Kind | Label | SI unit | Default | Range |
|---|---|---|---|---:|---:|
| `minimum_active_coverage_pct` | `percent` | Min active coverage | % | 5.0 | 0.0–100.0 |
| `startup_delay_min` | `duration_minutes` | Startup delay | min | 0.0 | 0.0–60.0 |
| `require_operational_gate` | `boolean` | Require operational gate | boolean | 1.0 | 0.0–1.0 |
| `confirm_seconds` | `duration_seconds` | Confirm time | s | 900.0 | 0.0–3600.0 |
| `sat_err` | `temperature_difference` | SAT vs SP leak ΔT | Δ°C | 1.111111 | 0.277778–4.444444 |
| `mat_leak_delta` | `temperature_difference` | SAT vs MAT leak ΔT | Δ°C | 1.111111 | 0.277778–6.666667 |


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
**Family:** `vav` · **Equipment:** `vav`, `zone_other`, `heatpump`, `baseboard`  
**Equation:** Zone temp outside `zone_lo`–`zone_hi` (default 21.11–23.89°C) during occupied hours when `occ_mode` is set (`require_occupied`, default on). A saved Overview calendar fills a missing or blank `occ_mode` before the rule runs. NULL `occ_mode` means neither the calendar nor a BAS occupied point is set, so every sample is scored. Unoccupied setback stays on VAV-2.  
**Default confirmation:** 900 s

| Parameter | Kind | Label | SI unit | Default | Range |
|---|---|---|---|---:|---:|
| `minimum_active_coverage_pct` | `percent` | Min active coverage | % | 5.0 | 0.0–100.0 |
| `startup_delay_min` | `duration_minutes` | Startup delay | min | 0.0 | 0.0–60.0 |
| `require_operational_gate` | `boolean` | Require operational gate | boolean | 1.0 | 0.0–1.0 |
| `zone_t_lo` | `absolute_temperature` | Zone low | °C | 21.111111111 | 12.777777778–22.222222222 |
| `zone_t_hi` | `absolute_temperature` | Zone high | °C | 23.888888889 | 22.222222222–29.444444444 |
| `require_occupied` | `boolean` | Require occupied | boolean | 1.0 | 0.0–1.0 |
| `confirm_seconds` | `duration_seconds` | Confirm time | s | 900 | 0–3600 |


```sql
-- confirmation_seconds: 900
-- See sql/fdd/postgres/rules/vav1_comfort_fault.sql
-- REQUIRE_OCCUPIED defaults to 1. Unoccupied tokens and numeric occ_mode <= 0.05
-- do not fault. NULL occ_mode does not suppress the band.
SELECT equipment_id, fault_hours, fault_pct FROM vav1_comfort_fault_result
```

### VAV-2 — Night setback miss
**Family:** `vav` · **Equipment:** `vav`, `zone`  
**Equation:** Unoccupied AND zone temp > setback_hi (default 20°C).  
**Default confirmation:** 900 s

| Parameter | Kind | Label | SI unit | Default | Range |
|---|---|---|---|---:|---:|
| `minimum_active_coverage_pct` | `percent` | Min active coverage | % | 5.0 | 0.0–100.0 |
| `startup_delay_min` | `duration_minutes` | Startup delay | min | 0.0 | 0.0–60.0 |
| `require_operational_gate` | `boolean` | Require operational gate | boolean | 1.0 | 0.0–1.0 |
| `setback_hi` | `absolute_temperature` | Setback high | °C | 20.0 | 12.777777778–22.222222222 |
| `confirm_seconds` | `duration_seconds` | Confirm time | s | 900 | 0–3600 |


```sql
-- confirmation_seconds: 900
-- See sql/fdd/postgres/rules/vav2_night_setback.sql
SELECT equipment_id, fault_hours FROM vav2_night_setback_result
```

### VAV-3 — Excessive reheat during warm weather
**Family:** `vav` · **Equipment:** `vav`  
**Equation:** Air flowing AND OAT > 25.56°C AND reheat valve > 52%.  
**Default confirmation:** 300 s

| Parameter | Kind | Label | SI unit | Default | Range |
|---|---|---|---|---:|---:|
| `minimum_active_coverage_pct` | `percent` | Min active coverage | % | 5.0 | 0.0–100.0 |
| `startup_delay_min` | `duration_minutes` | Startup delay | min | 0.0 | 0.0–60.0 |
| `require_operational_gate` | `boolean` | Require operational gate | boolean | 1.0 | 0.0–1.0 |
| `confirm_seconds` | `duration_seconds` | Confirm time | s | 300.0 | 0.0–3600.0 |
| `reheat_oat` | `absolute_temperature` | Warm OAT | °C | 25.555555556 | 18.333333333–32.222222222 |
| `reheat_pct` | `fraction` | Reheat frac | frac | 0.52 | 0.1–1.0 |
| `flow_on_min` | `volumetric_flow` | Airflow-on min | L/s | 11.798675 | 0.0–94.3894 |


```sql
-- confirmation_seconds: 300
-- rule: VAV-3 — Excessive reheat during warm weather
-- equation: Air flowing AND OAT > 25.555556°C AND reheat valve > 52%.

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

| Parameter | Kind | Label | SI unit | Default | Range |
|---|---|---|---|---:|---:|
| `minimum_active_coverage_pct` | `percent` | Min active coverage | % | 5.0 | 0.0–100.0 |
| `startup_delay_min` | `duration_minutes` | Startup delay | min | 0.0 | 0.0–60.0 |
| `require_operational_gate` | `boolean` | Require operational gate | boolean | 1.0 | 0.0–1.0 |
| `confirm_seconds` | `duration_seconds` | Confirm time | s | 900.0 | 0.0–3600.0 |
| `full_open_pct` | `fraction` | Full open frac | frac | 0.975 | 0.8–1.0 |
| `flow_on_min` | `volumetric_flow` | Airflow-on min | L/s | 11.798675 | 0.0–94.3894 |
| `sustain_hours` | `dimensionless` | Sustain window | h | 1.5 | 0.5–6.0 |


```sql
-- Sequential: (1) sustain full-open streak (2) confirm that mask — not max(sustain, confirm).
-- See sql/fdd/postgres/rules/vav4_damper_full_open.sql
SELECT equipment_id, fault_hours FROM vav4_damper_full_open_result
```

### VAV-5 — Airflow sensor bias
**Family:** `vav` · **Equipment:** `vav`  
**Equation:** Airflow > 23.597 L/s while damper < 10% (implausible flow).  
**Default confirmation:** 900 s

_No tunable thresholds beyond confirmation delay._

```sql
-- confirmation_seconds: 900
-- rule: VAV-5 — Airflow sensor bias
-- equation: Airflow > 23.59735 L/s while damper < 10% (implausible flow).

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

### VAV-6 — Reheat when cooling available
**Family:** `vav` · **Equipment:** `vav`  
**Equation:** OAT < 18.33°C AND reheat valve > 25% (optional cooling-available).  
**Default confirmation:** 900 s

{: .important }
**SI SQL parity:** P2 SQL SI for `VAV-6` remains **pending** on the si-parity gate until plant-family SQL SI is qualified on fixtures (pandas SI may run; do not edit frozen IP goldens or globally enable SQL SI to greenwash the matrix).

| Parameter | Kind | Label | SI unit | Default | Range |
|---|---|---|---|---:|---:|
| `minimum_active_coverage_pct` | `percent` | Min active coverage | % | 5.0 | 0.0–100.0 |
| `startup_delay_min` | `duration_minutes` | Startup delay | min | 0.0 | 0.0–60.0 |
| `require_operational_gate` | `boolean` | Require operational gate | boolean | 1.0 | 0.0–1.0 |
| `free_cool_oat` | `absolute_temperature` | Free-cool OAT | °C | 18.333333333 | 7.222222222–23.888888889 |
| `reheat_pct` | `fraction` | Reheat frac | frac | 0.25 | 0.05–1.0 |
| `confirm_seconds` | `duration_seconds` | Confirm time | s | 900.0 | 0.0–3600.0 |


```sql
-- confirmation_seconds: 900
-- See sql/fdd/postgres/rules/vav6_reheat_free_cool.sql
SELECT equipment_id, fault_hours FROM vav6_reheat_free_cool_result
```

### VAV-REHEAT — Reheat valve stuck / no temp rise
**Family:** `vav` · **Equipment:** `vav`  
**Equation:** Air flowing AND reheat valve > 30% AND box discharge temp rises < 1.67Δ°C above duct inlet (air from AHU) — stuck or failed reheat valve/coil.  
**Default confirmation:** 900 s

| Parameter | Kind | Label | SI unit | Default | Range |
|---|---|---|---|---:|---:|
| `minimum_active_coverage_pct` | `percent` | Min active coverage | % | 5.0 | 0.0–100.0 |
| `startup_delay_min` | `duration_minutes` | Startup delay | min | 0.0 | 0.0–60.0 |
| `require_operational_gate` | `boolean` | Require operational gate | boolean | 1.0 | 0.0–1.0 |
| `confirm_seconds` | `duration_seconds` | Confirm time | s | 900.0 | 0.0–3600.0 |
| `reheat_cmd` | `fraction` | Reheat open frac | frac | 0.3 | 0.1–1.0 |
| `min_rise` | `temperature_difference` | Min temp rise | °C | 1.666666667 | 0.277777778–8.333333333 |
| `flow_on_min` | `volumetric_flow` | Airflow-on min | L/s | 11.798675 | 0.0–94.3894 |


```sql
-- confirmation_seconds: 900
-- rule: VAV-REHEAT — Reheat valve stuck / no temp rise
-- equation: Air flowing AND reheat valve > 30% AND box discharge temp rises < 1.666667Δ°C above duct inlet (air from AHU) — stuck or failed reheat valve/coil.

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

| Parameter | Kind | Label | SI unit | Default | Range |
|---|---|---|---|---:|---:|
| `confirm_seconds` | `duration_seconds` | Confirm time | s | 900.0 | 0.0–3600.0 |
| `delta` | `temperature_difference` | Leave Δ vs AHU SAT | °C | 4.444444444 | 1.111111111–13.888888889 |
| `flow_on_min` | `volumetric_flow` | Airflow-on min | L/s | 11.798675 | 0.0–94.3894 |


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

| Parameter | Kind | Label | SI unit | Default | Range |
|---|---|---|---|---:|---:|
| `minimum_active_coverage_pct` | `percent` | Min active coverage | % | 5.0 | 0.0–100.0 |
| `startup_delay_min` | `duration_minutes` | Startup delay | min | 0.0 | 0.0–60.0 |
| `require_operational_gate` | `boolean` | Require operational gate | boolean | 1.0 | 0.0–1.0 |
| `confirm_seconds` | `duration_seconds` | Confirm time | s | 900.0 | 0.0–3600.0 |
| `high_min_flow_sp` | `volumetric_flow` | High min-flow SP | L/s | 117.98675 | 23.59735–943.894 |
| `flow_on_min` | `volumetric_flow` | Airflow-on min | L/s | 11.798675 | 0.0–94.3894 |
| `fixed_flow_hours` | `dimensionless` | Fixed-flow rolling window | h | 1.0 | 0.25–6.0 |
| `fixed_flow_max_std` | `volumetric_flow` | Fixed-flow max std | L/s | 7.079205 | 0.471947–37.75576 |
| `fixed_flow_min_mean` | `volumetric_flow` | Fixed-flow min mean | L/s | 94.3894 | 23.59735–943.894 |


```sql
-- confirmation_seconds: 900
-- Three pandas branches: under-min OR fixed-high rolling std/mean OR high min_flow_sp.
-- SQL: sql/fdd/postgres/rules/vav7_min_airflow.sql (timestamp-ordered windows).
SELECT equipment_id, fault_hours FROM vav7_min_airflow_result
```

## Fan coil / zone_other

Nine `FCU-*` rules. This section sits in the same family order as the [Pandas cookbook](pandas-cookbook.html#fan-coil--zone_other): after VAV terminals, before central plant. Each rule below uses the same equation, parameter table, and confirmation seconds as that page. Family `fcu`, priority P1, `dashboard_wired: false`. Registry and pandas equipment kinds are `zone_other`, `general`, and `ahu`. Haystack stacks markers on one equip (`equip` + `fanCoilUnit` + `zone`) and on each point (`zone` + `air` + `temp`, valve cmds, and the other roles below). Open-FDD consumes that as a stamp plus mapped roles. A sensor-owning master stamps `canonical_kind` `zone_other` (`equipType` `zone_other`, `zone`, `fcu`, `fanCoil`, or a standalone-DDC alias). A follower without its own zone sensor is resolved kind `general`. A fan coil's stamp stays `zone_other`. Kind `ahu` is on the list so a stamped air handler that carries these roles can run the family. The equipment id is only the historian key. Stamps and the SI unit contract: [FCU and zone_other rules](fcu-zone-other.html).

**Parity:** `sql_screening`. These pages document the tip predicates. They do not promote the family. Soft-OPEN closes only after tip and field stress on issue-mapped gates (mask and duration versus the pandas oracle). Cookbook CI and unit fixtures are not that gate. This docs change does not add a stress-script stub.

Commands accept 0–1 or 0–100 (`> 1.0` divides by 100). Valve-shut tests use a fixed `0.05`. CO₂ below `300` ppm does not fault. Fan proof prefers status, with normalized `fan_cmd > 0.10` when status is null. PostgreSQL treats non-null `fan_status` as on above `0.05`. Pandas `as_bool` treats non-null numeric `fan-status` as on above `0.5`. That cut is part of why the family stays `sql_screening`.

Six duration rules (`FCU-HTG-COIL`, `FCU-CLG-COIL`, `FCU-VALVE-PASS-HTG`, `FCU-VALVE-PASS-CLG`, `FCU-DAMPER-POS`, `FCU-CO2-DAMPER`) confirm for **900 s**. `FCU-SENSOR-NULL`, `FCU-DEADBAND`, and `FCU-MODE-CYCLE` confirm for **0 s**.

PostgreSQL files `sql/fdd/postgres/rules/fcu_*.sql` emit `fault_hours`. The six duration files share a normalized CTE and a consecutive streak: `{{CONFIRM_ROWS}}` = ceil(`confirm_seconds` / poll seconds), minimum 1, then hours = confirmed rows × `{{POLL_SECONDS}} / 3600`. The CASE blocks below are the `raw_fault` predicates from those files. Pandas twins return a raw mask; `confirm_fault` returns that mask unchanged when `confirm_seconds` is 0. The `confirm_min` slider default is `confirm_seconds / 60` after catalog load.

SQL registry `optional_roles` also name columns the shared CTE selects (the other valve, dampers, CO₂) when that rule's predicate does not test them. Pandas reads only the roles listed on each rule. A package that maps every **required** role plus fan proof can run both engines. Missing SQL-only optional columns are NULL in PostgreSQL. Role map for later tip stress: [zone terminals]({{ site.baseurl }}/modeling/zone-terminals/) and [SQL rules → Haystack]({{ site.baseurl }}/modeling/sql-rules-haystack-map.html).

### FCU-SENSOR-NULL — Missing FCU zone sensor
**Family:** `fcu` · **Equipment:** `zone_other`, `general`, `ahu` · **Parity:** `sql_screening`  
**Equation:** Own zone setpoint is present, and zone temperature is null for at least 90% of those rows (`null_fraction`).  
**Default confirmation:** 0 s  
**Required roles (both engines):** pandas `zone-air-temp-sp` → SQL `zone_air_temp_sp`  
**Optional roles (both engines):** pandas `zone-air-temp` → SQL `zone_t`

**Tunable params**

| Parameter | Kind | Label | SI unit | Default | Range |
|---|---|---|---|---:|---:|
| `null_fraction` | `fraction` | Null fraction | frac | 0.9 | 0.5–1 |


When `zone_t` is absent from history, the runner rewrites this file to zero hours. A setpoint-only follower must not look like a dead sensor. A mapped `zone_t` column that is present and null still runs the SQL below (`sql/fdd/postgres/rules/fcu_sensor_null.sql`).

```sql
-- FCU-SENSOR-NULL — own zone setpoint exists while a mapped zone sensor is predominantly null.
WITH coverage AS (
  SELECT equipment_id,
    SUM(CASE WHEN zone_air_temp_sp IS NOT NULL THEN 1 ELSE 0 END) AS eligible_rows,
    SUM(CASE WHEN zone_air_temp_sp IS NOT NULL AND zone_t IS NULL THEN 1 ELSE 0 END) AS null_rows
  FROM history
  GROUP BY equipment_id
)
SELECT equipment_id,
  CASE WHEN eligible_rows > 0 AND CAST(null_rows AS DOUBLE) / eligible_rows >= {{NULL_FRACTION}}
    THEN null_rows * {{POLL_SECONDS}} / 3600.0 ELSE 0.0 END AS fault_hours
FROM coverage;
```

### FCU-HTG-COIL — FCU heating coil under-delivery
**Family:** `fcu` · **Equipment:** `zone_other`, `general`, `ahu` · **Parity:** `sql_screening`  
**Equation:** Fan on, heating valve ≥ 80% (`valve_open`), and discharge air − zone temperature < 3Δ°C (`coil_delta`, Δ°C).  
**Default confirmation:** 900 s  
**Required roles (both engines):** pandas `discharge-air-temp`, `zone-air-temp`, `heating-valve` → SQL `sat`, `zone_t`, `htg_valve_pct`  
**Optional roles (both engines):** pandas `fan-status`, `fan-cmd` → SQL `fan_status`, `fan_cmd`  
**SQL registry also optional** (shared CTE; pandas predicate does not read them): `clg_valve_pct`, `damper_cmd`, `damper_pct`, `zone_co2`

**Tunable params**

| Parameter | Kind | Label | SI unit | Default | Range |
|---|---|---|---|---:|---:|
| `valve_open` | `fraction` | Valve open threshold | frac | 0.8 | 0.5–1 |
| `coil_delta` | `temperature_difference` | Minimum heating rise | °C | 3.0 | 0.555555556–11.111111111 |


`sat` and `zone_t` are normalized to °C. `coil_delta` is a Δ°C threshold. Predicate from `sql/fdd/postgres/rules/fcu_htg_coil.sql` (shared streak tail follows):

```sql
CAST(CASE
  WHEN sat IS NOT NULL AND zone_t IS NOT NULL AND fan_on = 1
   AND htg >= {{VALVE_OPEN}}
   AND sat - zone_t < {{COIL_DELTA}}
  THEN 1 ELSE 0 END AS INT) AS raw_fault
```

### FCU-CLG-COIL — FCU cooling coil under-delivery
**Family:** `fcu` · **Equipment:** `zone_other`, `general`, `ahu` · **Parity:** `sql_screening`  
**Equation:** Fan on, cooling valve ≥ 80% (`valve_open`), heating valve ≤ 0.05, and discharge air − zone temperature ≥ 0.  
**Default confirmation:** 900 s  
**Required roles (both engines):** pandas `discharge-air-temp`, `zone-air-temp`, `cooling-valve`, `heating-valve` → SQL `sat`, `zone_t`, `clg_valve_pct`, `htg_valve_pct`  
**Optional roles (both engines):** pandas `fan-status`, `fan-cmd` → SQL `fan_status`, `fan_cmd`  
**SQL registry also optional** (shared CTE; pandas predicate does not read them): `damper_cmd`, `damper_pct`, `zone_co2`

**Tunable params**

| Parameter | Kind | Label | SI unit | Default | Range |
|---|---|---|---|---:|---:|
| `valve_open` | `fraction` | Valve open threshold | frac | 0.8 | 0.5–1 |


The “not colder than the zone” test is fixed at `sat - zone_t >= 0`. There is no delta slider. Predicate from `sql/fdd/postgres/rules/fcu_clg_coil.sql`:

```sql
CAST(CASE
  WHEN sat IS NOT NULL AND zone_t IS NOT NULL AND fan_on = 1
   AND clg >= {{VALVE_OPEN}} AND htg <= 0.05
   AND sat - zone_t >= 0.0
  THEN 1 ELSE 0 END AS INT) AS raw_fault
```

### FCU-VALVE-PASS-HTG — FCU heating valve passing
**Family:** `fcu` · **Equipment:** `zone_other`, `general`, `ahu` · **Parity:** `sql_screening`  
**Equation:** Fan on, both valves ≤ 0.05, and discharge air − zone temperature > 3Δ°C (`pass_delta`).  
**Default confirmation:** 900 s  
**Required roles (both engines):** pandas `discharge-air-temp`, `zone-air-temp`, `heating-valve`, `cooling-valve` → SQL `sat`, `zone_t`, `htg_valve_pct`, `clg_valve_pct`  
**Optional roles (both engines):** pandas `fan-status`, `fan-cmd` → SQL `fan_status`, `fan_cmd`  
**SQL registry also optional** (shared CTE; pandas predicate does not read them): `damper_cmd`, `damper_pct`, `zone_co2`

**Tunable params**

| Parameter | Kind | Label | SI unit | Default | Range |
|---|---|---|---|---:|---:|
| `pass_delta` | `temperature_difference` | Passing temperature rise | °C | 3.0 | 0.555555556–11.111111111 |


Predicate from `sql/fdd/postgres/rules/fcu_valve_pass_htg.sql`:

```sql
CAST(CASE
  WHEN sat IS NOT NULL AND zone_t IS NOT NULL AND fan_on = 1
   AND htg <= 0.05 AND clg <= 0.05
   AND sat - zone_t > {{PASS_DELTA_F}}
  THEN 1 ELSE 0 END AS INT) AS raw_fault
```

### FCU-VALVE-PASS-CLG — FCU cooling valve passing
**Family:** `fcu` · **Equipment:** `zone_other`, `general`, `ahu` · **Parity:** `sql_screening`  
**Equation:** Fan on, both valves ≤ 0.05, and zone temperature − discharge air > 3Δ°C (`pass_delta`).  
**Default confirmation:** 900 s  
**Required roles (both engines):** pandas `discharge-air-temp`, `zone-air-temp`, `heating-valve`, `cooling-valve` → SQL `sat`, `zone_t`, `htg_valve_pct`, `clg_valve_pct`  
**Optional roles (both engines):** pandas `fan-status`, `fan-cmd` → SQL `fan_status`, `fan_cmd`  
**SQL registry also optional** (shared CTE; pandas predicate does not read them): `damper_cmd`, `damper_pct`, `zone_co2`

**Tunable params**

| Parameter | Kind | Label | SI unit | Default | Range |
|---|---|---|---|---:|---:|
| `pass_delta` | `temperature_difference` | Passing temperature drop | °C | 3.0 | 0.555555556–11.111111111 |


Predicate from `sql/fdd/postgres/rules/fcu_valve_pass_clg.sql`:

```sql
CAST(CASE
  WHEN sat IS NOT NULL AND zone_t IS NOT NULL AND fan_on = 1
   AND htg <= 0.05 AND clg <= 0.05
   AND zone_t - sat > {{PASS_DELTA_F}}
  THEN 1 ELSE 0 END AS INT) AS raw_fault
```

### FCU-DAMPER-POS — FCU damper command/position mismatch
**Family:** `fcu` · **Equipment:** `zone_other`, `general`, `ahu` · **Parity:** `sql_screening`  
**Equation:** Fan on, damper command ≥ 15% (`command_min`), and command − feedback > 0.15 (`position_error`). Feedback above command is not a fault.  
**Default confirmation:** 900 s  
**Required roles (both engines):** pandas `damper-cmd`, `damper` → SQL `damper_cmd`, `damper_pct`  
**Optional roles (both engines):** pandas `fan-status`, `fan-cmd` → SQL `fan_status`, `fan_cmd`  
**SQL registry also optional** (shared CTE; pandas predicate does not read them): `sat`, `zone_t`, `htg_valve_pct`, `clg_valve_pct`, `zone_co2`

**Tunable params**

| Parameter | Kind | Label | SI unit | Default | Range |
|---|---|---|---|---:|---:|
| `command_min` | `fraction` | Minimum command | frac | 0.15 | 0–1 |
| `position_error` | `fraction` | Position error | frac | 0.15 | 0.05–0.5 |


Predicate from `sql/fdd/postgres/rules/fcu_damper_pos.sql`:

```sql
CAST(CASE
  WHEN fan_on = 1 AND dcmd IS NOT NULL AND dpos IS NOT NULL
   AND dcmd >= {{COMMAND_MIN}}
   AND dcmd - dpos > {{POSITION_ERROR}}
  THEN 1 ELSE 0 END AS INT) AS raw_fault
```

### FCU-CO2-DAMPER — FCU high CO₂ with low outdoor-air command
**Family:** `fcu` · **Equipment:** `zone_other`, `general`, `ahu` · **Parity:** `sql_screening`  
**Equation:** Fan on, zone CO₂ > 1000 ppm (`co2_high_ppm`) and CO₂ ≥ 300 ppm, and damper command < 10% (`damper_low`).  
**Default confirmation:** 900 s  
**Required roles (both engines):** pandas `zone-co2`, `damper-cmd` → SQL `zone_co2`, `damper_cmd`  
**Optional roles (both engines):** pandas `fan-status`, `fan-cmd` → SQL `fan_status`, `fan_cmd`  
**SQL registry also optional** (shared CTE; pandas predicate does not read them): `sat`, `zone_t`, `htg_valve_pct`, `clg_valve_pct`, `damper_pct`

**Tunable params**

| Parameter | Kind | Label | SI unit | Default | Range |
|---|---|---|---|---:|---:|
| `co2_high_ppm` | `dimensionless` | High CO2 | ppm | 1000 | 600–2000 |
| `damper_low` | `fraction` | Low damper command | frac | 0.1 | 0–0.5 |


Predicate from `sql/fdd/postgres/rules/fcu_co2_damper.sql`:

```sql
CAST(CASE
  WHEN fan_on = 1 AND zone_co2 IS NOT NULL
   AND zone_co2 > {{CO2_HIGH_PPM}} AND zone_co2 >= 300.0
   AND dcmd IS NOT NULL AND dcmd < {{DAMPER_LOW}}
  THEN 1 ELSE 0 END AS INT) AS raw_fault
```

### FCU-DEADBAND — FCU heat/cool deadband collapse
**Family:** `fcu` · **Equipment:** `zone_other`, `general`, `ahu` · **Parity:** `sql_screening`  
**Equation:** Cooling setpoint − heating setpoint < 1Δ°C (`deadband`). Both source values are normalized to °C at ingest; the difference is evaluated in Δ°C.  
**Default confirmation:** 0 s  
**Required roles (both engines):** pandas `cooling-sp`, `heating-sp` → SQL `cooling_sp`, `heating_sp`  
**Optional roles (both engines):** none

**Tunable params**

| Parameter | Kind | Label | SI unit | Default | Range |
|---|---|---|---|---:|---:|
| `deadband` | `temperature_difference` | Minimum deadband | °C | 1 | 0–5 |


`cooling_sp` and `heating_sp` are engineer-declared point roles normalized to °C at ingest. Their difference and the `deadband` parameter use Δ°C. Full file `sql/fdd/postgres/rules/fcu_deadband.sql`:

```sql
-- FCU-DEADBAND — pass-through FCU setpoints are normalized to °C
SELECT equipment_id,
  SUM(CASE WHEN cooling_sp IS NOT NULL AND heating_sp IS NOT NULL
    AND cooling_sp - heating_sp < {{DEADBAND_C}} THEN 1 ELSE 0 END)
    * {{POLL_SECONDS}} / 3600.0 AS fault_hours
FROM history
GROUP BY equipment_id;
```

### FCU-MODE-CYCLE — FCU heating/cooling mode cycling
**Family:** `fcu` · **Equipment:** `zone_other`, `general`, `ahu` · **Parity:** `sql_screening`  
**Equation:** At least four heating/cooling valve mode changes in the window (`mode_changes`). A valve is active above 10% (`mode_valve_min`). Cooling wins when both valves are active. Idle samples are omitted from the sequence and are not fault rows after the count crosses the threshold.  
**Default confirmation:** 0 s  
**Required roles (both engines):** pandas `heating-valve`, `cooling-valve` → SQL `htg_valve_pct`, `clg_valve_pct`  
**Optional roles (both engines):** none

**Tunable params**

| Parameter | Kind | Label | SI unit | Default | Range |
|---|---|---|---|---:|---:|
| `mode_valve_min` | `fraction` | Active valve threshold | frac | 0.1 | 0–0.5 |
| `mode_changes` | `count` | Mode changes | count | 4 | 1–20 |


Mode assignment from `sql/fdd/postgres/rules/fcu_mode_cycle.sql`. The rest of the file keeps `mode <> 0` rows, counts changes with `LAG`, and sums rows whose running `change_count` is at least `{{MODE_CHANGES}}`:

```sql
CASE
  WHEN clg_valve_pct IS NOT NULL
   AND (CASE WHEN clg_valve_pct > 1.0 THEN clg_valve_pct / 100.0 ELSE clg_valve_pct END) > {{MODE_VALVE_MIN}}
  THEN -1
  WHEN htg_valve_pct IS NOT NULL
   AND (CASE WHEN htg_valve_pct > 1.0 THEN htg_valve_pct / 100.0 ELSE htg_valve_pct END) > {{MODE_VALVE_MIN}}
  THEN 1
  ELSE 0
END AS mode
```

## Central plant / condenser water

### CHW-NOLOAD-1 — Chiller running with no building load
**Family:** `plant` · **Equipment:** `chiller`  
**Equation:** Chiller/plant proven running while building load is satisfied: all mapped zones inside comfort band OR all mapped AHU SAT within sat_band of setpoint. Default confirm 30 min.  
**Default confirmation:** 1800 s

| Parameter | Kind | Label | SI unit | Default | Range |
|---|---|---|---|---:|---:|
| `minimum_active_coverage_pct` | `percent` | Min active coverage | % | 5.0 | 0.0–100.0 |
| `startup_delay_min` | `duration_minutes` | Startup delay | min | 0.0 | 0.0–60.0 |
| `require_operational_gate` | `boolean` | Require operational gate | boolean | 1.0 | 0.0–1.0 |
| `confirm_seconds` | `duration_seconds` | Confirm time | s | 1800.0 | 0.0–3600.0 |
| `load_sat_hi` | `fraction` | Load satisfaction high (no-load fault) | frac | 0.5 | 0.0–1.0 |


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
**Equation:** Pump on AND (CHWR − CHWS) < 2.22Δ°C.  
**Default confirmation:** 900 s

| Parameter | Kind | Label | SI unit | Default | Range |
|---|---|---|---|---:|---:|
| `minimum_active_coverage_pct` | `percent` | Min active coverage | % | 5.0 | 0.0–100.0 |
| `startup_delay_min` | `duration_minutes` | Startup delay | min | 0.0 | 0.0–60.0 |
| `require_operational_gate` | `boolean` | Require operational gate | boolean | 1.0 | 0.0–1.0 |
| `confirm_seconds` | `duration_seconds` | Confirm time | s | 900.0 | 0.0–3600.0 |
| `min_dt` | `temperature_difference` | Minimum delta-T | °C | 2.222222 | 0.555556–6.666667 |


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

| Parameter | Kind | Label | SI unit | Default | Range |
|---|---|---|---|---:|---:|
| `minimum_active_coverage_pct` | `percent` | Min active coverage | % | 5.0 | 0.0–100.0 |
| `startup_delay_min` | `duration_minutes` | Startup delay | min | 0.0 | 0.0–60.0 |
| `require_operational_gate` | `boolean` | Require operational gate | boolean | 1.0 | 0.0–1.0 |
| `confirm_seconds` | `duration_seconds` | Confirm time | s | 300.0 | 0.0–3600.0 |
| `dp_margin` | `hydronic_pressure` | DP margin | kPa | 15.168465 | 3.447379–41.368542 |
| `pump_hi` | `fraction` | Pump high-speed threshold | frac | 0.87 | 0.5–1.0 |


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
**Equation:** Pump on AND |CHWS − CHWS SP| > 1.22Δ°C.  
**Default confirmation:** 300 s

| Parameter | Kind | Label | SI unit | Default | Range |
|---|---|---|---|---:|---:|
| `minimum_active_coverage_pct` | `percent` | Min active coverage | % | 5.0 | 0.0–100.0 |
| `startup_delay_min` | `duration_minutes` | Startup delay | min | 0.0 | 0.0–60.0 |
| `require_operational_gate` | `boolean` | Require operational gate | boolean | 1.0 | 0.0–1.0 |
| `confirm_seconds` | `duration_seconds` | Confirm time | s | 300.0 | 0.0–3600.0 |
| `sp_band` | `temperature_difference` | SP band | °C | 1.222222 | 0.277778–3.333333 |


```sql
-- confirmation_seconds: 300
-- rule: CHW-3 — Plant supply temp outside deadband
-- equation: Pump on AND |CHWS − CHWS SP| > 1.222222Δ°C.

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
**Equation:** Pump ≥ 87% AND CHW flow > 69.39922 L/s.  
**Default confirmation:** 300 s

| Parameter | Kind | Label | SI unit | Default | Range |
|---|---|---|---|---:|---:|
| `minimum_active_coverage_pct` | `percent` | Min active coverage | % | 5.0 | 0.0–100.0 |
| `startup_delay_min` | `duration_minutes` | Startup delay | min | 0.0 | 0.0–60.0 |
| `require_operational_gate` | `boolean` | Require operational gate | boolean | 1.0 | 0.0–1.0 |
| `confirm_seconds` | `duration_seconds` | Confirm time | s | 300.0 | 0.0–3600.0 |
| `flow_hi` | `volumetric_flow` | Flow high | L/s | 69.39922 | 12.61804–189.2706 |
| `pump_hi` | `fraction` | Pump high-speed threshold | frac | 0.87 | 0.5–1.0 |


```sql
-- confirmation_seconds: 300
-- rule: CHW-4 — Flow high at max pump
-- equation: Pump ≥ 87% AND CHW flow > 69.39922 L/s.

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

| Parameter | Kind | Label | SI unit | Default | Range |
|---|---|---|---|---:|---:|
| `minimum_active_coverage_pct` | `percent` | Min active coverage | % | 5.0 | 0.0–100.0 |
| `startup_delay_min` | `duration_minutes` | Startup delay | min | 0.0 | 0.0–60.0 |
| `require_operational_gate` | `boolean` | Require operational gate | boolean | 1.0 | 0.0–1.0 |
| `confirm_seconds` | `duration_seconds` | Confirm time | s | 900.0 | 0.0–3600.0 |
| `cw_approach` | `temperature_difference` | Design approach | °C | 3.888889 | 1.666667–8.333333 |
| `cw_slack` | `temperature_difference` | Slack below target | °C | 1.111111 | 0.277778–3.333333 |


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
**Equation:** At full tower fan speed, leaving CW − web wet-bulb exceeds approach_max (default 4.44Δ°C, typically 2.78–5.56Δ°C). Suspect OA→wet-bulb / CW sensor mismatch or cooling-tower performance degradation.  
**Default confirmation:** 900 s

| Parameter | Kind | Label | SI unit | Default | Range |
|---|---|---|---|---:|---:|
| `minimum_active_coverage_pct` | `percent` | Min active coverage | % | 5.0 | 0.0–100.0 |
| `startup_delay_min` | `duration_minutes` | Startup delay | min | 0.0 | 0.0–60.0 |
| `require_operational_gate` | `boolean` | Require operational gate | boolean | 1.0 | 0.0–1.0 |
| `confirm_seconds` | `duration_seconds` | Confirm time | s | 900.0 | 0.0–3600.0 |
| `approach_max` | `temperature_difference` | Max approach at full fan | °C | 4.444444 | 2.777778–8.333333 |
| `tower_fan_hi` | `fraction` | Tower fan full-speed threshold | frac | 0.95 | 0.8–1.0 |


```sql
-- confirmation_seconds: 900
-- rule: CW-APR-1 — High CW approach at full tower fan
-- equation: At full tower fan speed, leaving CW − web wet-bulb exceeds approach_max (default 4.444444Δ°C, typically 2.777778–5.555556Δ°C). Suspect OA→wet-bulb / CW sensor mismatch or cooling-tower performance degradation.

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

| Parameter | Kind | Label | SI unit | Default | Range |
|---|---|---|---|---:|---:|
| `minimum_active_coverage_pct` | `percent` | Min active coverage | % | 5.0 | 0.0–100.0 |
| `startup_delay_min` | `duration_minutes` | Startup delay | min | 0.0 | 0.0–60.0 |
| `require_operational_gate` | `boolean` | Require operational gate | boolean | 1.0 | 0.0–1.0 |
| `confirm_seconds` | `duration_seconds` | Confirm time | s | 900.0 | 0.0–3600.0 |
| `cw_approach` | `temperature_difference` | Design approach | °C | 3.888889 | 1.666667–8.333333 |
| `excess_beyond_approach` | `temperature_difference` | Excess beyond approach | °C | 2.777778 | 1.111111–11.111111 |
| `tower_fan_hi` | `fraction` | Tower fan full-speed threshold | frac | 0.95 | 0.8–1.0 |


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
**Equation:** Fan on, zone < 20.56°C, discharge SAT < 29.44°C.  
**Default confirmation:** 600 s

| Parameter | Kind | Label | SI unit | Default | Range |
|---|---|---|---|---:|---:|
| `minimum_active_coverage_pct` | `percent` | Min active coverage | % | 5.0 | 0.0–100.0 |
| `startup_delay_min` | `duration_minutes` | Startup delay | min | 0.0 | 0.0–60.0 |
| `require_operational_gate` | `boolean` | Require operational gate | boolean | 1.0 | 0.0–1.0 |
| `confirm_seconds` | `duration_seconds` | Confirm time | s | 600.0 | 0.0–3600.0 |
| `min_sat` | `absolute_temperature` | Min discharge SAT | °C | 29.444444 | 21.111111–43.333333 |
| `zone_cold` | `absolute_temperature` | Zone cold threshold | °C | 20.555556 | 15.555556–22.222222 |


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
**Equation:** OAT sample-to-sample jump > 8.89Δ°C.  
**Default confirmation:** 300 s

| Parameter | Kind | Label | SI unit | Default | Range |
|---|---|---|---|---:|---:|
| `confirm_seconds` | `duration_seconds` | Confirm time | s | 300.0 | 0.0–3600.0 |
| `spike_limit` | `temperature_difference` | Spike limit | °C | 8.888889 | 2.222222–22.222222 |


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
**Equation:** Duct static high (> 335.93 Pa) while VAV pressure requests are low.  
**Default confirmation:** 1800 s

| Parameter | Kind | Label | SI unit | Default | Range |
|---|---|---|---|---:|---:|
| `minimum_active_coverage_pct` | `percent` | Min active coverage | % | 5.0 | 0.0–100.0 |
| `startup_delay_min` | `duration_minutes` | Startup delay | min | 0.0 | 0.0–60.0 |
| `require_operational_gate` | `boolean` | Require operational gate | boolean | 1.0 | 0.0–1.0 |
| `confirm_seconds` | `duration_seconds` | Confirm time | s | 1800.0 | 0.0–3600.0 |
| `duct_hi` | `air_pressure` | Duct static high | Pa | 335.934 | 124.42–746.52 |
| `request_lo` | `count` | Request sum low | count | 1.0 | 0.0–10.0 |


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
**Equation:** HW supply > 71.11°C while reset requests are low.  
**Default confirmation:** 1800 s

| Parameter | Kind | Label | SI unit | Default | Range |
|---|---|---|---|---:|---:|
| `minimum_active_coverage_pct` | `percent` | Min active coverage | % | 5.0 | 0.0–100.0 |
| `startup_delay_min` | `duration_minutes` | Startup delay | min | 0.0 | 0.0–60.0 |
| `require_operational_gate` | `boolean` | Require operational gate | boolean | 1.0 | 0.0–1.0 |
| `confirm_seconds` | `duration_seconds` | Confirm time | s | 1800.0 | 0.0–3600.0 |
| `hwst_hi` | `absolute_temperature` | HWST high | °C | 71.111111 | 48.888889–93.333333 |
| `request_lo` | `count` | Request sum low | count | 1.0 | 0.0–10.0 |


```sql
-- confirmation_seconds: 1800
-- rule: TRIM-3 — HWST trim advisory
-- equation: HW supply > 71.111111°C while reset requests are low.

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
**Equation:** CHW supply < 7.22°C while reset requests are low.  
**Default confirmation:** 1800 s

| Parameter | Kind | Label | SI unit | Default | Range |
|---|---|---|---|---:|---:|
| `minimum_active_coverage_pct` | `percent` | Min active coverage | % | 5.0 | 0.0–100.0 |
| `startup_delay_min` | `duration_minutes` | Startup delay | min | 0.0 | 0.0–60.0 |
| `require_operational_gate` | `boolean` | Require operational gate | boolean | 1.0 | 0.0–1.0 |
| `confirm_seconds` | `duration_seconds` | Confirm time | s | 1800.0 | 0.0–3600.0 |
| `chw_lo` | `absolute_temperature` | CHWS low | °C | 7.222222 | 1.666667–12.777778 |
| `request_lo` | `count` | Request sum low | count | 1.0 | 0.0–10.0 |


```sql
-- confirmation_seconds: 1800
-- rule: TRIM-4 — CHW plant reset advisory
-- equation: CHW supply < 7.222222°C while reset requests are low.

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
**Equation:** Fan running while occupancy is unoccupied (Overview calendar → occ_mode). When zone_t is mapped, also require zone inside `comfort_low`…`comfort_high` (defaults 21.11–23.89°C; synced from Overview zone band).  
**Default confirmation:** 1800 s

| Parameter | Kind | Label | SI unit | Default | Range |
|---|---|---|---|---:|---:|
| `confirm_seconds` | `duration_seconds` | Confirm time | s | 1800.0 | 0.0–3600.0 |
| `comfort_low` | `absolute_temperature` | Zone comfort low | °C | 21.111111 | 10.0–26.666667 |
| `comfort_high` | `absolute_temperature` | Zone comfort high | °C | 23.888889 | 12.777778–32.222222 |


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

| Parameter | Kind | Label | SI unit | Default | Range |
|---|---|---|---|---:|---:|
| `confirm_seconds` | `duration_seconds` | Confirm time | s | 3600.0 | 0.0–3600.0 |
| `always_on_pct` | `fraction` | Always-on fraction | frac | 0.95 | 0.8–1.0 |


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
| `TOWER-1` | Cooling tower approach high | `plant` |
| `CTRL-2` | Generic control loop hunting | `control` |
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

<!-- shipped-sql:start -->

## Shipped SQL files

These are the PostgreSQL files the product runs, copied from `sql/fdd/postgres/rules/` plus `postgres_helpers.sql`. Tokens in double braces, such as FLATLINE_ROWS, are fill-in parameters.

| File |
| --- |
| [`ahu_ducthi.sql`](#ahu_ducthisql) |
| [`ahu_satdev.sql`](#ahu_satdevsql) |
| [`ahu_simul.sql`](#ahu_simulsql) |
| [`avg_zone_temp.sql`](#avg_zone_tempsql) |
| [`chw1_low_dt.sql`](#chw1_low_dtsql) |
| [`chw2_dp_low.sql`](#chw2_dp_lowsql) |
| [`chw3_supply_band.sql`](#chw3_supply_bandsql) |
| [`chw4_flow_high.sql`](#chw4_flow_highsql) |
| [`chw_noload_1.sql`](#chw_noload_1sql) |
| [`cmd1_fan_mismatch.sql`](#cmd1_fan_mismatchsql) |
| [`cw_apr_1.sql`](#cw_apr_1sql) |
| [`cw_fan_1.sql`](#cw_fan_1sql) |
| [`cw_opt_1.sql`](#cw_opt_1sql) |
| [`dmp1_oa_damper_leak.sql`](#dmp1_oa_damper_leaksql) |
| [`econ1_stuck_closed.sql`](#econ1_stuck_closedsql) |
| [`econ3_mech_without_econ.sql`](#econ3_mech_without_econsql) |
| [`econ4_low_oa_frac.sql`](#econ4_low_oa_fracsql) |
| [`econ5_preheat_over.sql`](#econ5_preheat_oversql) |
| [`econ6_econ_freezing.sql`](#econ6_econ_freezingsql) |
| [`econ7_ok_not_economizing.sql`](#econ7_ok_not_economizingsql) |
| [`economizer_fault.sql`](#economizer_faultsql) |
| [`fan_runtime_hours.sql`](#fan_runtime_hourssql) |
| [`fault_elapsed_hours.sql`](#fault_elapsed_hourssql) |
| [`fc10_mat_oa_clg.sql`](#fc10_mat_oa_clgsql) |
| [`fc11_oa_sat_sp_clg.sql`](#fc11_oa_sat_sp_clgsql) |
| [`fc12_sat_mat_clg.sql`](#fc12_sat_mat_clgsql) |
| [`fc14_chw_coil_dt_inactive.sql`](#fc14_chw_coil_dt_inactivesql) |
| [`fc15_hw_coil_dt_inactive.sql`](#fc15_hw_coil_dt_inactivesql) |
| [`fc1_duct_static_low.sql`](#fc1_duct_static_lowsql) |
| [`fc2_mat_low.sql`](#fc2_mat_lowsql) |
| [`fc3_mat_high.sql`](#fc3_mat_highsql) |
| [`fc4_os_hunting.sql`](#fc4_os_huntingsql) |
| [`fc5_sat_cold_heating.sql`](#fc5_sat_cold_heatingsql) |
| [`fc6_oa_frac_mismatch.sql`](#fc6_oa_frac_mismatchsql) |
| [`fc7_sat_low_heating.sql`](#fc7_sat_low_heatingsql) |
| [`fc8_sat_mat_econ.sql`](#fc8_sat_mat_econsql) |
| [`fc9_oa_sat_sp_econ.sql`](#fc9_oa_sat_sp_econsql) |
| [`fcu_clg_coil.sql`](#fcu_clg_coilsql) |
| [`fcu_co2_damper.sql`](#fcu_co2_dampersql) |
| [`fcu_damper_pos.sql`](#fcu_damper_possql) |
| [`fcu_deadband.sql`](#fcu_deadbandsql) |
| [`fcu_htg_coil.sql`](#fcu_htg_coilsql) |
| [`fcu_mode_cycle.sql`](#fcu_mode_cyclesql) |
| [`fcu_sensor_null.sql`](#fcu_sensor_nullsql) |
| [`fcu_valve_pass_clg.sql`](#fcu_valve_pass_clgsql) |
| [`fcu_valve_pass_htg.sql`](#fcu_valve_pass_htgsql) |
| [`hp1_discharge_cold.sql`](#hp1_discharge_coldsql) |
| [`mech_oat_1.sql`](#mech_oat_1sql) |
| [`oa1_low_oa_frac.sql`](#oa1_low_oa_fracsql) |
| [`oat_meteo_fault.sql`](#oat_meteo_faultsql) |
| [`pid_hunt_1.sql`](#pid_hunt_1sql) |
| [`reset1_sat_oa_reset.sql`](#reset1_sat_oa_resetsql) |
| [`sat_high_fault.sql`](#sat_high_faultsql) |
| [`sched1_unoccupied_runtime.sql`](#sched1_unoccupied_runtimesql) |
| [`sched247_always_on.sql`](#sched247_always_onsql) |
| [`sv_flatline.sql`](#sv_flatlinesql) |
| [`sv_range.sql`](#sv_rangesql) |
| [`sv_rate.sql`](#sv_ratesql) |
| [`sv_spike.sql`](#sv_spikesql) |
| [`sv_stale.sql`](#sv_stalesql) |
| [`trim1_duct_static.sql`](#trim1_duct_staticsql) |
| [`trim3_hwst.sql`](#trim3_hwstsql) |
| [`trim4_chw_reset.sql`](#trim4_chw_resetsql) |
| [`util_interval_fault.sql`](#util_interval_faultsql) |
| [`util_monthly_fault.sql`](#util_monthly_faultsql) |
| [`vav1_comfort_fault.sql`](#vav1_comfort_faultsql) |
| [`vav2_night_setback.sql`](#vav2_night_setbacksql) |
| [`vav3_excessive_reheat.sql`](#vav3_excessive_reheatsql) |
| [`vav4_damper_full_open.sql`](#vav4_damper_full_opensql) |
| [`vav5_airflow_bias.sql`](#vav5_airflow_biassql) |
| [`vav6_reheat_free_cool.sql`](#vav6_reheat_free_coolsql) |
| [`vav7_min_airflow.sql`](#vav7_min_airflowsql) |
| [`vav_ahu_leave.sql`](#vav_ahu_leavesql) |
| [`vav_reheat.sql`](#vav_reheatsql) |
| [`vlv1_clg_valve_leak.sql`](#vlv1_clg_valve_leaksql) |
| [`wx1_oa_spike.sql`](#wx1_oa_spikesql) |
| [`zone_comfort_pct.sql`](#zone_comfort_pctsql) |
| [`postgres_helpers.sql`](#postgres_helperssql) |

### ahu_ducthi.sql

`sql/fdd/postgres/rules/ahu_ducthi.sql`

{% raw %}
```sql
-- PostgreSQL adaptation. Render numeric template parameters with render_rule.py.
-- Inputs must be scoped to one tenant/site and cadence; see README.md.
-- ahu_ducthi.sql — Duct static pressure high
-- Equation: static > SP + DUCT_HIGH_MARGIN.
-- Gate: fan-on from fan_status then fan_cmd. Missing fan stays NULL
-- (do not ELSE 1). Pressure-on substitutes only when fan proof is absent,
-- never when status/cmd is proven 0 (frozen overnight static).
WITH h AS (
  SELECT
    equipment_id,
    timestamp_utc,
    duct_static, duct_static_sp,
    CASE WHEN fan_cmd IS NULL THEN NULL WHEN fan_cmd > 1.0 THEN fan_cmd / 100.0 ELSE fan_cmd END AS fan,
    CASE
      WHEN fan_status IS NOT NULL THEN CASE WHEN fan_status > 0.05 THEN 1 ELSE 0 END
      WHEN fan_cmd IS NOT NULL THEN CASE WHEN (CASE WHEN fan_cmd > 1.0 THEN fan_cmd / 100.0 ELSE fan_cmd END) > 0.01 THEN 1 ELSE 0 END
      ELSE NULL
    END AS fan_on
  FROM history
),
base AS (
  SELECT
    equipment_id,
    timestamp_utc,
    CAST(CASE
      WHEN duct_static IS NULL OR duct_static_sp IS NULL THEN 0
      WHEN fan_on = 0 THEN 0
      WHEN fan_on = 1 AND duct_static > duct_static_sp + {{DUCT_HIGH_MARGIN}} THEN 1
      WHEN fan_on IS NULL
           AND ABS(duct_static) > {{PRESSURE_ON_MIN}}
           AND duct_static > duct_static_sp + {{DUCT_HIGH_MARGIN}} THEN 1
      ELSE 0
    END AS INT) AS raw_fault
  FROM h
),
elapsed_hold AS (
  -- Forward sample-and-hold. A gap longer than MAX_GAP_HOURS is unknown:
  -- it is not fault time, not covered time, and it breaks confirmation.
  -- The last sample has no forward interval.
  SELECT
    stepped.*,
    CASE
      WHEN stepped.dt_seconds IS NULL
        OR stepped.dt_seconds <= 0.0
        OR stepped.dt_seconds > ({{MAX_GAP_HOURS}} * 3600.0)
      THEN 0.0
      ELSE stepped.dt_seconds
    END AS held_seconds,
    CASE
      WHEN stepped.dt_seconds > ({{MAX_GAP_HOURS}} * 3600.0) THEN 1
      ELSE 0
    END AS gap_after
  FROM (
    SELECT
      src.*,
      EXTRACT(EPOCH FROM (
        LEAD(src.timestamp_utc) OVER (
          PARTITION BY src.equipment_id ORDER BY src.timestamp_utc
        ) - src.timestamp_utc
      )) AS dt_seconds
    FROM base src
  ) stepped
),
lagged AS (
  SELECT
    *,
    CASE
      WHEN raw_fault = LAG(raw_fault) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc)
       AND COALESCE(LAG(gap_after) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc), 0) = 0
      THEN 0 ELSE 1
    END AS is_new_streak
  FROM elapsed_hold
),
grp AS (
  SELECT
    *,
    SUM(is_new_streak)
      OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS UNBOUNDED PRECEDING) AS streak_id
  FROM lagged
),
ranked AS (
  SELECT
    *,
    SUM(held_seconds) OVER (
      PARTITION BY equipment_id, streak_id ORDER BY timestamp_utc
      ROWS UNBOUNDED PRECEDING
    ) AS streak_elapsed
  FROM grp
),
final AS (
  SELECT
    equipment_id,
    held_seconds,
    CASE WHEN raw_fault = 1 AND streak_elapsed >= {{CONFIRM_SECONDS}} THEN 1 ELSE 0 END AS confirmed
  FROM ranked
)
SELECT
  equipment_id,
  SUM(CASE WHEN confirmed = 1 THEN held_seconds ELSE 0.0 END) / 3600.0 AS fault_hours,
  SUM(held_seconds) / 3600.0 AS covered_hours,
  100.0 * SUM(CASE WHEN confirmed = 1 THEN held_seconds ELSE 0.0 END) / NULLIF(SUM(held_seconds), 0.0) AS fault_pct
FROM final
GROUP BY equipment_id;
```
{% endraw %}

### ahu_satdev.sql

`sql/fdd/postgres/rules/ahu_satdev.sql`

{% raw %}
```sql
-- PostgreSQL adaptation. Render numeric template parameters with render_rule.py.
-- Inputs must be scoped to one tenant/site and cadence; see README.md.
-- ahu_satdev.sql — SAT deviation from setpoint (fan_running + confirm)
-- Gate: fan-on from fan_status then fan_cmd. Missing fan stays off
-- (do not ELSE 1 / COALESCE to on — that invents on-hours).
-- Quality (#1253): SQL does NOT apply open_fdd.quality OUT_OF_RANGE/sentinel
-- nulling. Pandas SQL parity must use quality=False; run_rule(quality=True) is
-- a different surface.
WITH h AS (
  SELECT
    equipment_id,
    timestamp_utc,
    sat,
    sat_sp,
    fan_cmd,
    fan_status,
    CASE
      WHEN fan_status IS NOT NULL THEN CASE WHEN fan_status > 0.05 THEN 1 ELSE 0 END
      WHEN fan_cmd IS NOT NULL THEN CASE WHEN (CASE WHEN fan_cmd > 1.0 THEN fan_cmd / 100.0 ELSE fan_cmd END) > 0.01 THEN 1 ELSE 0 END
      ELSE 0
    END AS fan_on
  FROM history
),
base AS (
  SELECT
    equipment_id,
    timestamp_utc,
    CAST(CASE
      WHEN COALESCE(fan_on, 0) = 0 THEN 0
      WHEN sat IS NULL OR sat_sp IS NULL THEN 0
      WHEN ABS(sat - sat_sp) > {{SAT_DEV_ERR}} THEN 1
      ELSE 0
    END AS INT) AS raw_fault
  FROM h
),
elapsed_hold AS (
  -- Forward sample-and-hold. A gap longer than MAX_GAP_HOURS is unknown:
  -- it is not fault time, not covered time, and it breaks confirmation.
  -- The last sample has no forward interval.
  SELECT
    stepped.*,
    CASE
      WHEN stepped.dt_seconds IS NULL
        OR stepped.dt_seconds <= 0.0
        OR stepped.dt_seconds > ({{MAX_GAP_HOURS}} * 3600.0)
      THEN 0.0
      ELSE stepped.dt_seconds
    END AS held_seconds,
    CASE
      WHEN stepped.dt_seconds > ({{MAX_GAP_HOURS}} * 3600.0) THEN 1
      ELSE 0
    END AS gap_after
  FROM (
    SELECT
      src.*,
      EXTRACT(EPOCH FROM (
        LEAD(src.timestamp_utc) OVER (
          PARTITION BY src.equipment_id ORDER BY src.timestamp_utc
        ) - src.timestamp_utc
      )) AS dt_seconds
    FROM base src
  ) stepped
),
lagged AS (
  SELECT
    *,
    CASE
      WHEN raw_fault = LAG(raw_fault) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc)
       AND COALESCE(LAG(gap_after) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc), 0) = 0
      THEN 0 ELSE 1
    END AS is_new_streak
  FROM elapsed_hold
),
grp AS (
  SELECT
    *,
    SUM(is_new_streak)
      OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS UNBOUNDED PRECEDING) AS streak_id
  FROM lagged
),
ranked AS (
  SELECT
    *,
    SUM(held_seconds) OVER (
      PARTITION BY equipment_id, streak_id ORDER BY timestamp_utc
      ROWS UNBOUNDED PRECEDING
    ) AS streak_elapsed
  FROM grp
),
final AS (
  SELECT
    equipment_id,
    held_seconds,
    CASE WHEN raw_fault = 1 AND streak_elapsed >= {{CONFIRM_SECONDS}} THEN 1 ELSE 0 END AS confirmed
  FROM ranked
)
SELECT
  equipment_id,
  SUM(CASE WHEN confirmed = 1 THEN held_seconds ELSE 0.0 END) / 3600.0 AS fault_hours,
  SUM(held_seconds) / 3600.0 AS covered_hours,
  100.0 * SUM(CASE WHEN confirmed = 1 THEN held_seconds ELSE 0.0 END) / NULLIF(SUM(held_seconds), 0.0) AS fault_pct
FROM final
GROUP BY equipment_id;
```
{% endraw %}

### ahu_simul.sql

`sql/fdd/postgres/rules/ahu_simul.sql`

{% raw %}
```sql
-- PostgreSQL adaptation. Render numeric template parameters with render_rule.py.
-- Inputs must be scoped to one tenant/site and cadence; see README.md.
-- ahu_simul.sql — Heating and cooling simultaneous
WITH h AS (
  SELECT
    equipment_id,
    timestamp_utc,
    CASE WHEN htg_valve_pct IS NULL THEN NULL WHEN htg_valve_pct > 1.0 THEN htg_valve_pct / 100.0 ELSE htg_valve_pct END AS htg,
    CASE WHEN clg_valve_pct IS NULL THEN NULL WHEN clg_valve_pct > 1.0 THEN clg_valve_pct / 100.0 ELSE clg_valve_pct END AS clg,
    fan_cmd,
    fan_status,
    CASE
      WHEN fan_status IS NOT NULL THEN CASE WHEN fan_status > 0.05 THEN 1 ELSE 0 END
      WHEN fan_cmd IS NOT NULL THEN CASE WHEN (CASE WHEN fan_cmd > 1.0 THEN fan_cmd / 100.0 ELSE fan_cmd END) > 0.01 THEN 1 ELSE 0 END
      ELSE 1
    END AS fan_on

  FROM history
),
base AS (
  SELECT
    equipment_id,
    timestamp_utc,
    CAST(CASE
      WHEN COALESCE(fan_on, 1) = 0 THEN 0
      WHEN htg IS NULL OR clg IS NULL THEN 0
      WHEN htg > {{VALVE_OPEN_PCT}} AND clg > {{VALVE_OPEN_PCT}} THEN 1
      ELSE 0
    END AS INT) AS raw_fault
  FROM h
),
elapsed_hold AS (
  -- Forward sample-and-hold. A gap longer than MAX_GAP_HOURS is unknown:
  -- it is not fault time, not covered time, and it breaks confirmation.
  -- The last sample has no forward interval.
  SELECT
    stepped.*,
    CASE
      WHEN stepped.dt_seconds IS NULL
        OR stepped.dt_seconds <= 0.0
        OR stepped.dt_seconds > ({{MAX_GAP_HOURS}} * 3600.0)
      THEN 0.0
      ELSE stepped.dt_seconds
    END AS held_seconds,
    CASE
      WHEN stepped.dt_seconds > ({{MAX_GAP_HOURS}} * 3600.0) THEN 1
      ELSE 0
    END AS gap_after
  FROM (
    SELECT
      src.*,
      EXTRACT(EPOCH FROM (
        LEAD(src.timestamp_utc) OVER (
          PARTITION BY src.equipment_id ORDER BY src.timestamp_utc
        ) - src.timestamp_utc
      )) AS dt_seconds
    FROM base src
  ) stepped
),
lagged AS (
  SELECT
    *,
    CASE
      WHEN raw_fault = LAG(raw_fault) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc)
       AND COALESCE(LAG(gap_after) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc), 0) = 0
      THEN 0 ELSE 1
    END AS is_new_streak
  FROM elapsed_hold
),
grp AS (
  SELECT
    *,
    SUM(is_new_streak)
      OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS UNBOUNDED PRECEDING) AS streak_id
  FROM lagged
),
ranked AS (
  SELECT
    *,
    SUM(held_seconds) OVER (
      PARTITION BY equipment_id, streak_id ORDER BY timestamp_utc
      ROWS UNBOUNDED PRECEDING
    ) AS streak_elapsed
  FROM grp
),
final AS (
  SELECT
    equipment_id,
    held_seconds,
    CASE WHEN raw_fault = 1 AND streak_elapsed >= {{CONFIRM_SECONDS}} THEN 1 ELSE 0 END AS confirmed
  FROM ranked
)
SELECT
  equipment_id,
  SUM(CASE WHEN confirmed = 1 THEN held_seconds ELSE 0.0 END) / 3600.0 AS fault_hours,
  SUM(held_seconds) / 3600.0 AS covered_hours,
  100.0 * SUM(CASE WHEN confirmed = 1 THEN held_seconds ELSE 0.0 END) / NULLIF(SUM(held_seconds), 0.0) AS fault_pct
FROM final
GROUP BY equipment_id;
```
{% endraw %}

### avg_zone_temp.sql

`sql/fdd/postgres/rules/avg_zone_temp.sql`

{% raw %}
```sql
-- PostgreSQL adaptation. Render numeric template parameters with render_rule.py.
-- Inputs must be scoped to one tenant/site and cadence; see README.md.
-- avg_zone_temp.sql
SELECT
  equipment_id,
  AVG(zone_t) AS avg_zone_temp,
  MIN(zone_t) AS min_zone_temp,
  MAX(zone_t) AS max_zone_temp
FROM history
WHERE zone_t IS NOT NULL
GROUP BY equipment_id;
```
{% endraw %}

### chw1_low_dt.sql

`sql/fdd/postgres/rules/chw1_low_dt.sql`

{% raw %}
```sql
-- PostgreSQL adaptation. Render numeric template parameters with render_rule.py.
-- Inputs must be scoped to one tenant/site and cadence; see README.md.
-- chw1_low_dt.sql — Low chilled-water ΔT
-- Operational proof required: status / current / power / flow / pump cmd.
-- Missing proof → 0 fault hours (pandas twin returns SKIPPED_MISSING_ROLES).
-- Proven off (zeros) → 0 fault hours.
WITH h AS (
  SELECT
    equipment_id,
    timestamp_utc,
    chw_supply_t, chw_return_t,
    CASE WHEN chw_pump_cmd IS NULL THEN NULL WHEN chw_pump_cmd > 1.0 THEN chw_pump_cmd / 100.0 ELSE chw_pump_cmd END AS pump,
    chiller_status,
    chiller_current,
    chiller_amps,
    chiller_power,
    chw_flow,
    pump_status
  FROM history
),
proof AS (
  SELECT
    *,
    CASE
      WHEN pump_status IS NOT NULL THEN CASE WHEN pump_status > 0.05 THEN 1 ELSE 0 END
      WHEN chiller_status IS NOT NULL THEN CASE WHEN chiller_status > 0.05 THEN 1 ELSE 0 END
      WHEN chiller_current IS NOT NULL THEN CASE WHEN chiller_current > 0.5 THEN 1 ELSE 0 END
      WHEN chiller_amps IS NOT NULL THEN CASE WHEN chiller_amps > 0.5 THEN 1 ELSE 0 END
      WHEN chiller_power IS NOT NULL THEN CASE WHEN chiller_power > 0.5 THEN 1 ELSE 0 END
      WHEN chw_flow IS NOT NULL THEN CASE WHEN chw_flow > 1.0 THEN 1 ELSE 0 END
      WHEN pump IS NOT NULL THEN CASE WHEN pump > 0.05 THEN 1 ELSE 0 END
      ELSE NULL
    END AS proof_on
  FROM h
),
base AS (
  SELECT
    equipment_id,
    timestamp_utc,
    CAST(CASE
      WHEN chw_supply_t IS NULL OR chw_return_t IS NULL THEN 0
      WHEN proof_on IS NULL THEN 0
      WHEN proof_on = 0 THEN 0
      WHEN (chw_return_t - chw_supply_t) < {{MIN_DT}} THEN 1
      ELSE 0
    END AS INT) AS raw_fault
  FROM proof
),
elapsed_hold AS (
  -- Forward sample-and-hold. A gap longer than MAX_GAP_HOURS is unknown:
  -- it is not fault time, not covered time, and it breaks confirmation.
  -- The last sample has no forward interval.
  SELECT
    stepped.*,
    CASE
      WHEN stepped.dt_seconds IS NULL
        OR stepped.dt_seconds <= 0.0
        OR stepped.dt_seconds > ({{MAX_GAP_HOURS}} * 3600.0)
      THEN 0.0
      ELSE stepped.dt_seconds
    END AS held_seconds,
    CASE
      WHEN stepped.dt_seconds > ({{MAX_GAP_HOURS}} * 3600.0) THEN 1
      ELSE 0
    END AS gap_after
  FROM (
    SELECT
      src.*,
      EXTRACT(EPOCH FROM (
        LEAD(src.timestamp_utc) OVER (
          PARTITION BY src.equipment_id ORDER BY src.timestamp_utc
        ) - src.timestamp_utc
      )) AS dt_seconds
    FROM base src
  ) stepped
),
lagged AS (
  SELECT
    *,
    CASE
      WHEN raw_fault = LAG(raw_fault) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc)
       AND COALESCE(LAG(gap_after) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc), 0) = 0
      THEN 0 ELSE 1
    END AS is_new_streak
  FROM elapsed_hold
),
grp AS (
  SELECT
    *,
    SUM(is_new_streak)
      OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS UNBOUNDED PRECEDING) AS streak_id
  FROM lagged
),
ranked AS (
  SELECT
    *,
    SUM(held_seconds) OVER (
      PARTITION BY equipment_id, streak_id ORDER BY timestamp_utc
      ROWS UNBOUNDED PRECEDING
    ) AS streak_elapsed
  FROM grp
),
final AS (
  SELECT
    equipment_id,
    held_seconds,
    CASE WHEN raw_fault = 1 AND streak_elapsed >= {{CONFIRM_SECONDS}} THEN 1 ELSE 0 END AS confirmed
  FROM ranked
)
SELECT
  equipment_id,
  SUM(CASE WHEN confirmed = 1 THEN held_seconds ELSE 0.0 END) / 3600.0 AS fault_hours,
  SUM(held_seconds) / 3600.0 AS covered_hours,
  100.0 * SUM(CASE WHEN confirmed = 1 THEN held_seconds ELSE 0.0 END) / NULLIF(SUM(held_seconds), 0.0) AS fault_pct
FROM final
GROUP BY equipment_id;
```
{% endraw %}

### chw2_dp_low.sql

`sql/fdd/postgres/rules/chw2_dp_low.sql`

{% raw %}
```sql
-- PostgreSQL adaptation. Render numeric template parameters with render_rule.py.
-- Inputs must be scoped to one tenant/site and cadence; see README.md.
-- chw2_dp_low.sql — DP below SP at max pump speed
WITH h AS (
  SELECT
    equipment_id,
    timestamp_utc,
    chw_dp, chw_dp_sp,
    CASE WHEN chw_pump_cmd IS NULL THEN NULL WHEN chw_pump_cmd > 1.0 THEN chw_pump_cmd / 100.0 ELSE chw_pump_cmd END AS pump,
    pump_status, chiller_status, chw_flow
  FROM history
),
proof AS (
  SELECT
    *,
    CASE
      WHEN pump_status IS NOT NULL THEN CASE WHEN pump_status > 0.05 THEN 1 ELSE 0 END
      WHEN chiller_status IS NOT NULL THEN CASE WHEN chiller_status > 0.05 THEN 1 ELSE 0 END
      WHEN chw_flow IS NOT NULL THEN CASE WHEN chw_flow > 1.0 THEN 1 ELSE 0 END
      WHEN pump IS NOT NULL THEN CASE WHEN pump > 0.05 THEN 1 ELSE 0 END
      ELSE NULL
    END AS proof_on
  FROM h
),
base AS (
  SELECT
    equipment_id,
    timestamp_utc,
    CAST(CASE
      WHEN proof_on IS NULL OR proof_on = 0 THEN 0
      WHEN chw_dp IS NULL OR chw_dp_sp IS NULL OR pump IS NULL THEN 0
      WHEN pump >= {{PUMP_HI}} AND chw_dp < chw_dp_sp - {{DP_MARGIN}} THEN 1
      ELSE 0
    END AS INT) AS raw_fault
  FROM proof
),
elapsed_hold AS (
  -- Forward sample-and-hold. A gap longer than MAX_GAP_HOURS is unknown:
  -- it is not fault time, not covered time, and it breaks confirmation.
  -- The last sample has no forward interval.
  SELECT
    stepped.*,
    CASE
      WHEN stepped.dt_seconds IS NULL
        OR stepped.dt_seconds <= 0.0
        OR stepped.dt_seconds > ({{MAX_GAP_HOURS}} * 3600.0)
      THEN 0.0
      ELSE stepped.dt_seconds
    END AS held_seconds,
    CASE
      WHEN stepped.dt_seconds > ({{MAX_GAP_HOURS}} * 3600.0) THEN 1
      ELSE 0
    END AS gap_after
  FROM (
    SELECT
      src.*,
      EXTRACT(EPOCH FROM (
        LEAD(src.timestamp_utc) OVER (
          PARTITION BY src.equipment_id ORDER BY src.timestamp_utc
        ) - src.timestamp_utc
      )) AS dt_seconds
    FROM base src
  ) stepped
),
lagged AS (
  SELECT
    *,
    CASE
      WHEN raw_fault = LAG(raw_fault) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc)
       AND COALESCE(LAG(gap_after) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc), 0) = 0
      THEN 0 ELSE 1
    END AS is_new_streak
  FROM elapsed_hold
),
grp AS (
  SELECT
    *,
    SUM(is_new_streak)
      OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS UNBOUNDED PRECEDING) AS streak_id
  FROM lagged
),
ranked AS (
  SELECT
    *,
    SUM(held_seconds) OVER (
      PARTITION BY equipment_id, streak_id ORDER BY timestamp_utc
      ROWS UNBOUNDED PRECEDING
    ) AS streak_elapsed
  FROM grp
),
final AS (
  SELECT
    equipment_id,
    held_seconds,
    CASE WHEN raw_fault = 1 AND streak_elapsed >= {{CONFIRM_SECONDS}} THEN 1 ELSE 0 END AS confirmed
  FROM ranked
)
SELECT
  equipment_id,
  SUM(CASE WHEN confirmed = 1 THEN held_seconds ELSE 0.0 END) / 3600.0 AS fault_hours,
  SUM(held_seconds) / 3600.0 AS covered_hours,
  100.0 * SUM(CASE WHEN confirmed = 1 THEN held_seconds ELSE 0.0 END) / NULLIF(SUM(held_seconds), 0.0) AS fault_pct
FROM final
GROUP BY equipment_id;
```
{% endraw %}

### chw3_supply_band.sql

`sql/fdd/postgres/rules/chw3_supply_band.sql`

{% raw %}
```sql
-- PostgreSQL adaptation. Render numeric template parameters with render_rule.py.
-- Inputs must be scoped to one tenant/site and cadence; see README.md.
-- chw3_supply_band.sql — Plant supply temp outside deadband
WITH h AS (
  SELECT
    equipment_id,
    timestamp_utc,
    chw_supply_t, chw_supply_sp,
    CASE WHEN chw_pump_cmd IS NULL THEN NULL WHEN chw_pump_cmd > 1.0 THEN chw_pump_cmd / 100.0 ELSE chw_pump_cmd END AS pump,
    pump_status, chiller_status, chw_flow
  FROM history
),
proof AS (
  SELECT *,
    CASE
      WHEN pump_status IS NOT NULL THEN CASE WHEN pump_status > 0.05 THEN 1 ELSE 0 END
      WHEN chiller_status IS NOT NULL THEN CASE WHEN chiller_status > 0.05 THEN 1 ELSE 0 END
      WHEN chw_flow IS NOT NULL THEN CASE WHEN chw_flow > 1.0 THEN 1 ELSE 0 END
      WHEN pump IS NOT NULL THEN CASE WHEN pump > 0.05 THEN 1 ELSE 0 END
      ELSE NULL
    END AS proof_on
  FROM h
),
base AS (
  SELECT
    equipment_id,
    timestamp_utc,
    CAST(CASE
      WHEN proof_on IS NULL OR proof_on = 0 THEN 0
      WHEN chw_supply_t IS NULL OR chw_supply_sp IS NULL THEN 0
      WHEN ABS(chw_supply_t - chw_supply_sp) > {{SP_BAND}} THEN 1
      ELSE 0
    END AS INT) AS raw_fault
  FROM proof
),
elapsed_hold AS (
  -- Forward sample-and-hold. A gap longer than MAX_GAP_HOURS is unknown:
  -- it is not fault time, not covered time, and it breaks confirmation.
  -- The last sample has no forward interval.
  SELECT
    stepped.*,
    CASE
      WHEN stepped.dt_seconds IS NULL
        OR stepped.dt_seconds <= 0.0
        OR stepped.dt_seconds > ({{MAX_GAP_HOURS}} * 3600.0)
      THEN 0.0
      ELSE stepped.dt_seconds
    END AS held_seconds,
    CASE
      WHEN stepped.dt_seconds > ({{MAX_GAP_HOURS}} * 3600.0) THEN 1
      ELSE 0
    END AS gap_after
  FROM (
    SELECT
      src.*,
      EXTRACT(EPOCH FROM (
        LEAD(src.timestamp_utc) OVER (
          PARTITION BY src.equipment_id ORDER BY src.timestamp_utc
        ) - src.timestamp_utc
      )) AS dt_seconds
    FROM base src
  ) stepped
),
lagged AS (
  SELECT
    *,
    CASE
      WHEN raw_fault = LAG(raw_fault) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc)
       AND COALESCE(LAG(gap_after) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc), 0) = 0
      THEN 0 ELSE 1
    END AS is_new_streak
  FROM elapsed_hold
),
grp AS (
  SELECT
    *,
    SUM(is_new_streak)
      OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS UNBOUNDED PRECEDING) AS streak_id
  FROM lagged
),
ranked AS (
  SELECT
    *,
    SUM(held_seconds) OVER (
      PARTITION BY equipment_id, streak_id ORDER BY timestamp_utc
      ROWS UNBOUNDED PRECEDING
    ) AS streak_elapsed
  FROM grp
),
final AS (
  SELECT
    equipment_id,
    held_seconds,
    CASE WHEN raw_fault = 1 AND streak_elapsed >= {{CONFIRM_SECONDS}} THEN 1 ELSE 0 END AS confirmed
  FROM ranked
)
SELECT
  equipment_id,
  SUM(CASE WHEN confirmed = 1 THEN held_seconds ELSE 0.0 END) / 3600.0 AS fault_hours,
  SUM(held_seconds) / 3600.0 AS covered_hours,
  100.0 * SUM(CASE WHEN confirmed = 1 THEN held_seconds ELSE 0.0 END) / NULLIF(SUM(held_seconds), 0.0) AS fault_pct
FROM final
GROUP BY equipment_id;
```
{% endraw %}

### chw4_flow_high.sql

`sql/fdd/postgres/rules/chw4_flow_high.sql`

{% raw %}
```sql
-- PostgreSQL adaptation. Render numeric template parameters with render_rule.py.
-- Inputs must be scoped to one tenant/site and cadence; see README.md.
-- chw4_flow_high.sql — Flow high at max pump
WITH h AS (
  SELECT
    equipment_id,
    timestamp_utc,
    chw_flow,
    CASE WHEN chw_pump_cmd IS NULL THEN NULL WHEN chw_pump_cmd > 1.0 THEN chw_pump_cmd / 100.0 ELSE chw_pump_cmd END AS pump,
    pump_status, chiller_status
  FROM history
),
proof AS (
  SELECT *,
    CASE
      WHEN pump_status IS NOT NULL THEN CASE WHEN pump_status > 0.05 THEN 1 ELSE 0 END
      WHEN chiller_status IS NOT NULL THEN CASE WHEN chiller_status > 0.05 THEN 1 ELSE 0 END
      WHEN pump IS NOT NULL THEN CASE WHEN pump > 0.05 THEN 1 ELSE 0 END
      ELSE NULL
    END AS proof_on
  FROM h
),
base AS (
  SELECT
    equipment_id,
    timestamp_utc,
    CAST(CASE
      WHEN proof_on IS NULL OR proof_on = 0 THEN 0
      WHEN chw_flow IS NULL OR pump IS NULL THEN 0
      WHEN pump >= {{PUMP_HI}} AND chw_flow > {{FLOW_HI}} THEN 1
      ELSE 0
    END AS INT) AS raw_fault
  FROM proof
),
elapsed_hold AS (
  -- Forward sample-and-hold. A gap longer than MAX_GAP_HOURS is unknown:
  -- it is not fault time, not covered time, and it breaks confirmation.
  -- The last sample has no forward interval.
  SELECT
    stepped.*,
    CASE
      WHEN stepped.dt_seconds IS NULL
        OR stepped.dt_seconds <= 0.0
        OR stepped.dt_seconds > ({{MAX_GAP_HOURS}} * 3600.0)
      THEN 0.0
      ELSE stepped.dt_seconds
    END AS held_seconds,
    CASE
      WHEN stepped.dt_seconds > ({{MAX_GAP_HOURS}} * 3600.0) THEN 1
      ELSE 0
    END AS gap_after
  FROM (
    SELECT
      src.*,
      EXTRACT(EPOCH FROM (
        LEAD(src.timestamp_utc) OVER (
          PARTITION BY src.equipment_id ORDER BY src.timestamp_utc
        ) - src.timestamp_utc
      )) AS dt_seconds
    FROM base src
  ) stepped
),
lagged AS (
  SELECT
    *,
    CASE
      WHEN raw_fault = LAG(raw_fault) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc)
       AND COALESCE(LAG(gap_after) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc), 0) = 0
      THEN 0 ELSE 1
    END AS is_new_streak
  FROM elapsed_hold
),
grp AS (
  SELECT
    *,
    SUM(is_new_streak)
      OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS UNBOUNDED PRECEDING) AS streak_id
  FROM lagged
),
ranked AS (
  SELECT
    *,
    SUM(held_seconds) OVER (
      PARTITION BY equipment_id, streak_id ORDER BY timestamp_utc
      ROWS UNBOUNDED PRECEDING
    ) AS streak_elapsed
  FROM grp
),
final AS (
  SELECT
    equipment_id,
    held_seconds,
    CASE WHEN raw_fault = 1 AND streak_elapsed >= {{CONFIRM_SECONDS}} THEN 1 ELSE 0 END AS confirmed
  FROM ranked
)
SELECT
  equipment_id,
  SUM(CASE WHEN confirmed = 1 THEN held_seconds ELSE 0.0 END) / 3600.0 AS fault_hours,
  SUM(held_seconds) / 3600.0 AS covered_hours,
  100.0 * SUM(CASE WHEN confirmed = 1 THEN held_seconds ELSE 0.0 END) / NULLIF(SUM(held_seconds), 0.0) AS fault_pct
FROM final
GROUP BY equipment_id;
```
{% endraw %}

### chw_noload_1.sql

`sql/fdd/postgres/rules/chw_noload_1.sql`

{% raw %}
```sql
-- PostgreSQL adaptation. Render numeric template parameters with render_rule.py.
-- Inputs must be scoped to one tenant/site and cadence; see README.md.
-- chw_noload_1.sql — Chiller running with no building load
-- When both zone and AHU load-satisfied flags are null, emit
-- SKIPPED_MISSING_ROLES (do not PASS 0 h). Prefer load_satisfaction
-- enrichment pandas uses when those columns are mapped.
WITH h AS (
  SELECT
    equipment_id,
    timestamp_utc,
    chiller_status,
    chiller_cmd,
    chw_pump_status,
    CASE WHEN chw_pump_cmd IS NULL THEN NULL WHEN chw_pump_cmd > 1.0 THEN chw_pump_cmd / 100.0 ELSE chw_pump_cmd END AS pump_cmd,
    building_zone_load_satisfied,
    building_ahu_load_satisfied,
    CASE
      WHEN building_zone_load_satisfied IS NOT NULL
        OR building_ahu_load_satisfied IS NOT NULL THEN 1
      ELSE 0
    END AS sat_present,
    COALESCE(building_zone_load_satisfied, building_ahu_load_satisfied) AS load_sat
  FROM history
),
proof AS (
  SELECT
    equipment_id,
    timestamp_utc,
    sat_present,
    load_sat,
    CASE
      WHEN chiller_status IS NULL AND chiller_cmd IS NULL
           AND chw_pump_status IS NULL AND pump_cmd IS NULL THEN NULL
      WHEN COALESCE(chiller_status, 0) > 0.05 THEN 1
      WHEN COALESCE(chiller_cmd, 0) > 0.05 THEN 1
      WHEN COALESCE(chw_pump_status, 0) > 0.05 THEN 1
      WHEN COALESCE(pump_cmd, 0) > 0.05 THEN 1
      ELSE 0
    END AS running
  FROM h
),
base AS (
  SELECT
    equipment_id,
    timestamp_utc,
    sat_present,
    CAST(CASE
      WHEN sat_present = 0 THEN 0
      WHEN running IS NULL OR load_sat IS NULL THEN 0
      WHEN running = 1 AND load_sat > {{LOAD_SAT_HI}} THEN 1
      ELSE 0
    END AS INT) AS raw_fault
  FROM proof
),
elapsed_hold AS (
  -- Forward sample-and-hold. A gap longer than MAX_GAP_HOURS is unknown:
  -- it is not fault time, not covered time, and it breaks confirmation.
  -- The last sample has no forward interval.
  SELECT
    stepped.*,
    CASE
      WHEN stepped.dt_seconds IS NULL
        OR stepped.dt_seconds <= 0.0
        OR stepped.dt_seconds > ({{MAX_GAP_HOURS}} * 3600.0)
      THEN 0.0
      ELSE stepped.dt_seconds
    END AS held_seconds,
    CASE
      WHEN stepped.dt_seconds > ({{MAX_GAP_HOURS}} * 3600.0) THEN 1
      ELSE 0
    END AS gap_after
  FROM (
    SELECT
      src.*,
      EXTRACT(EPOCH FROM (
        LEAD(src.timestamp_utc) OVER (
          PARTITION BY src.equipment_id ORDER BY src.timestamp_utc
        ) - src.timestamp_utc
      )) AS dt_seconds
    FROM base src
  ) stepped
),
lagged AS (
  SELECT
    *,
    CASE
      WHEN raw_fault = LAG(raw_fault) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc)
       AND COALESCE(LAG(gap_after) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc), 0) = 0
      THEN 0 ELSE 1
    END AS is_new_streak
  FROM elapsed_hold
),
grp AS (
  SELECT
    *,
    SUM(is_new_streak)
      OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS UNBOUNDED PRECEDING) AS streak_id
  FROM lagged
),
ranked AS (
  SELECT
    *,
    SUM(held_seconds) OVER (
      PARTITION BY equipment_id, streak_id ORDER BY timestamp_utc
      ROWS UNBOUNDED PRECEDING
    ) AS streak_elapsed
  FROM grp
),
final AS (
  SELECT
    equipment_id,
    held_seconds,
    sat_present,
    CASE WHEN raw_fault = 1 AND streak_elapsed >= {{CONFIRM_SECONDS}} THEN 1 ELSE 0 END AS confirmed
  FROM ranked
)
SELECT
  equipment_id,
  SUM(CASE WHEN confirmed = 1 THEN held_seconds ELSE 0.0 END) / 3600.0 AS fault_hours,
  SUM(held_seconds) / 3600.0 AS covered_hours,
  100.0 * SUM(CASE WHEN confirmed = 1 THEN held_seconds ELSE 0.0 END) / NULLIF(SUM(held_seconds), 0.0) AS fault_pct,
  CASE
    WHEN MAX(sat_present) = 0 THEN 'SKIPPED_MISSING_ROLES'
    WHEN SUM(confirmed) > 0 THEN 'FAULT'
    ELSE 'PASS'
  END AS status
FROM final
GROUP BY equipment_id;
```
{% endraw %}

### cmd1_fan_mismatch.sql

`sql/fdd/postgres/rules/cmd1_fan_mismatch.sql`

{% raw %}
```sql
-- PostgreSQL adaptation. Render numeric template parameters with render_rule.py.
-- Inputs must be scoped to one tenant/site and cadence; see README.md.
-- cmd1_fan_mismatch.sql — Fan cmd/status mismatch
WITH h AS (
  SELECT
    equipment_id,
    timestamp_utc,
    CASE WHEN fan_cmd IS NULL THEN NULL WHEN fan_cmd > 1.0 THEN fan_cmd / 100.0 ELSE fan_cmd END AS fan,
    fan_status
  FROM history
),
base AS (
  SELECT
    equipment_id,
    timestamp_utc,
        CAST(CASE
          WHEN fan IS NULL OR fan_status IS NULL THEN 0
          WHEN (fan >= 0.05) <> (fan_status > 0.5) THEN 1
          ELSE 0
        END AS INT) AS raw_fault
  FROM h
),
elapsed_hold AS (
  -- Forward sample-and-hold. A gap longer than MAX_GAP_HOURS is unknown:
  -- it is not fault time, not covered time, and it breaks confirmation.
  -- The last sample has no forward interval.
  SELECT
    stepped.*,
    CASE
      WHEN stepped.dt_seconds IS NULL
        OR stepped.dt_seconds <= 0.0
        OR stepped.dt_seconds > ({{MAX_GAP_HOURS}} * 3600.0)
      THEN 0.0
      ELSE stepped.dt_seconds
    END AS held_seconds,
    CASE
      WHEN stepped.dt_seconds > ({{MAX_GAP_HOURS}} * 3600.0) THEN 1
      ELSE 0
    END AS gap_after
  FROM (
    SELECT
      src.*,
      EXTRACT(EPOCH FROM (
        LEAD(src.timestamp_utc) OVER (
          PARTITION BY src.equipment_id ORDER BY src.timestamp_utc
        ) - src.timestamp_utc
      )) AS dt_seconds
    FROM base src
  ) stepped
),
lagged AS (
  SELECT
    *,
    CASE
      WHEN raw_fault = LAG(raw_fault) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc)
       AND COALESCE(LAG(gap_after) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc), 0) = 0
      THEN 0 ELSE 1
    END AS is_new_streak
  FROM elapsed_hold
),
grp AS (
  SELECT
    *,
    SUM(is_new_streak)
      OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS UNBOUNDED PRECEDING) AS streak_id
  FROM lagged
),
ranked AS (
  SELECT
    *,
    SUM(held_seconds) OVER (
      PARTITION BY equipment_id, streak_id ORDER BY timestamp_utc
      ROWS UNBOUNDED PRECEDING
    ) AS streak_elapsed
  FROM grp
),
final AS (
  SELECT
    equipment_id,
    held_seconds,
    CASE WHEN raw_fault = 1 AND streak_elapsed >= {{CONFIRM_SECONDS}} THEN 1 ELSE 0 END AS confirmed
  FROM ranked
)
SELECT
  equipment_id,
  SUM(CASE WHEN confirmed = 1 THEN held_seconds ELSE 0.0 END) / 3600.0 AS fault_hours,
  SUM(held_seconds) / 3600.0 AS covered_hours,
  100.0 * SUM(CASE WHEN confirmed = 1 THEN held_seconds ELSE 0.0 END) / NULLIF(SUM(held_seconds), 0.0) AS fault_pct
FROM final
GROUP BY equipment_id;
```
{% endraw %}

### cw_apr_1.sql

`sql/fdd/postgres/rules/cw_apr_1.sql`

{% raw %}
```sql
-- PostgreSQL adaptation. Render numeric template parameters with render_rule.py.
-- Inputs must be scoped to one tenant/site and cadence; see README.md.
-- cw_apr_1.sql — High CW approach at full tower fan
WITH h AS (
  SELECT
    equipment_id,
    timestamp_utc,
    cw_supply_t, web_wb_t,
    CASE WHEN tower_fan_cmd IS NULL THEN NULL WHEN tower_fan_cmd > 1.0 THEN tower_fan_cmd / 100.0 ELSE tower_fan_cmd END AS fan,
    pump_status,
    chiller_status,
    chw_flow,
    chw_pump_cmd,
    CASE
      WHEN pump_status IS NOT NULL THEN CASE WHEN pump_status > 0.05 THEN 1 ELSE 0 END
      WHEN chiller_status IS NOT NULL THEN CASE WHEN chiller_status > 0.05 THEN 1 ELSE 0 END
      WHEN chw_flow IS NOT NULL THEN CASE WHEN chw_flow > 1.0 THEN 1 ELSE 0 END
      WHEN chw_pump_cmd IS NOT NULL THEN CASE WHEN (CASE WHEN chw_pump_cmd > 1.0 THEN chw_pump_cmd / 100.0 ELSE chw_pump_cmd END) > 0.05 THEN 1 ELSE 0 END
      ELSE 0
    END AS proof_on

  FROM history
),
base AS (
  SELECT
    equipment_id,
    timestamp_utc,
    CAST(CASE
      WHEN COALESCE(proof_on, 0) = 0 THEN 0
      WHEN cw_supply_t IS NULL OR web_wb_t IS NULL OR fan IS NULL THEN 0
      WHEN fan >= {{TOWER_FAN_HI}}
       AND (cw_supply_t - web_wb_t) > {{APPROACH_MAX_F}} THEN 1
      ELSE 0
    END AS INT) AS raw_fault
  FROM h
),
elapsed_hold AS (
  -- Forward sample-and-hold. A gap longer than MAX_GAP_HOURS is unknown:
  -- it is not fault time, not covered time, and it breaks confirmation.
  -- The last sample has no forward interval.
  SELECT
    stepped.*,
    CASE
      WHEN stepped.dt_seconds IS NULL
        OR stepped.dt_seconds <= 0.0
        OR stepped.dt_seconds > ({{MAX_GAP_HOURS}} * 3600.0)
      THEN 0.0
      ELSE stepped.dt_seconds
    END AS held_seconds,
    CASE
      WHEN stepped.dt_seconds > ({{MAX_GAP_HOURS}} * 3600.0) THEN 1
      ELSE 0
    END AS gap_after
  FROM (
    SELECT
      src.*,
      EXTRACT(EPOCH FROM (
        LEAD(src.timestamp_utc) OVER (
          PARTITION BY src.equipment_id ORDER BY src.timestamp_utc
        ) - src.timestamp_utc
      )) AS dt_seconds
    FROM base src
  ) stepped
),
lagged AS (
  SELECT
    *,
    CASE
      WHEN raw_fault = LAG(raw_fault) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc)
       AND COALESCE(LAG(gap_after) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc), 0) = 0
      THEN 0 ELSE 1
    END AS is_new_streak
  FROM elapsed_hold
),
grp AS (
  SELECT
    *,
    SUM(is_new_streak)
      OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS UNBOUNDED PRECEDING) AS streak_id
  FROM lagged
),
ranked AS (
  SELECT
    *,
    SUM(held_seconds) OVER (
      PARTITION BY equipment_id, streak_id ORDER BY timestamp_utc
      ROWS UNBOUNDED PRECEDING
    ) AS streak_elapsed
  FROM grp
),
final AS (
  SELECT
    equipment_id,
    held_seconds,
    CASE WHEN raw_fault = 1 AND streak_elapsed >= {{CONFIRM_SECONDS}} THEN 1 ELSE 0 END AS confirmed
  FROM ranked
)
SELECT
  equipment_id,
  SUM(CASE WHEN confirmed = 1 THEN held_seconds ELSE 0.0 END) / 3600.0 AS fault_hours,
  SUM(held_seconds) / 3600.0 AS covered_hours,
  100.0 * SUM(CASE WHEN confirmed = 1 THEN held_seconds ELSE 0.0 END) / NULLIF(SUM(held_seconds), 0.0) AS fault_pct
FROM final
GROUP BY equipment_id;
```
{% endraw %}

### cw_fan_1.sql

`sql/fdd/postgres/rules/cw_fan_1.sql`

{% raw %}
```sql
-- PostgreSQL adaptation. Render numeric template parameters with render_rule.py.
-- Inputs must be scoped to one tenant/site and cadence; see README.md.
-- cw_fan_1.sql — Excess tower fan energy vs wet-bulb limit
WITH h AS (
  SELECT
    equipment_id,
    timestamp_utc,
    cw_supply_t, web_wb_t,
    CASE WHEN tower_fan_cmd IS NULL THEN NULL WHEN tower_fan_cmd > 1.0 THEN tower_fan_cmd / 100.0 ELSE tower_fan_cmd END AS fan,
    pump_status,
    chiller_status,
    chw_flow,
    chw_pump_cmd,
    CASE
      WHEN pump_status IS NOT NULL THEN CASE WHEN pump_status > 0.05 THEN 1 ELSE 0 END
      WHEN chiller_status IS NOT NULL THEN CASE WHEN chiller_status > 0.05 THEN 1 ELSE 0 END
      WHEN chw_flow IS NOT NULL THEN CASE WHEN chw_flow > 1.0 THEN 1 ELSE 0 END
      WHEN chw_pump_cmd IS NOT NULL THEN CASE WHEN (CASE WHEN chw_pump_cmd > 1.0 THEN chw_pump_cmd / 100.0 ELSE chw_pump_cmd END) > 0.05 THEN 1 ELSE 0 END
      ELSE 0
    END AS proof_on

  FROM history
),
base AS (
  SELECT
    equipment_id,
    timestamp_utc,
    CAST(CASE
      WHEN COALESCE(proof_on, 0) = 0 THEN 0
      WHEN cw_supply_t IS NULL OR web_wb_t IS NULL OR fan IS NULL THEN 0
      WHEN fan >= {{TOWER_FAN_HI}}
       AND cw_supply_t > web_wb_t + {{CW_APPROACH}} + {{EXCESS_BEYOND_APPROACH_F}} THEN 1
      ELSE 0
    END AS INT) AS raw_fault
  FROM h
),
elapsed_hold AS (
  -- Forward sample-and-hold. A gap longer than MAX_GAP_HOURS is unknown:
  -- it is not fault time, not covered time, and it breaks confirmation.
  -- The last sample has no forward interval.
  SELECT
    stepped.*,
    CASE
      WHEN stepped.dt_seconds IS NULL
        OR stepped.dt_seconds <= 0.0
        OR stepped.dt_seconds > ({{MAX_GAP_HOURS}} * 3600.0)
      THEN 0.0
      ELSE stepped.dt_seconds
    END AS held_seconds,
    CASE
      WHEN stepped.dt_seconds > ({{MAX_GAP_HOURS}} * 3600.0) THEN 1
      ELSE 0
    END AS gap_after
  FROM (
    SELECT
      src.*,
      EXTRACT(EPOCH FROM (
        LEAD(src.timestamp_utc) OVER (
          PARTITION BY src.equipment_id ORDER BY src.timestamp_utc
        ) - src.timestamp_utc
      )) AS dt_seconds
    FROM base src
  ) stepped
),
lagged AS (
  SELECT
    *,
    CASE
      WHEN raw_fault = LAG(raw_fault) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc)
       AND COALESCE(LAG(gap_after) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc), 0) = 0
      THEN 0 ELSE 1
    END AS is_new_streak
  FROM elapsed_hold
),
grp AS (
  SELECT
    *,
    SUM(is_new_streak)
      OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS UNBOUNDED PRECEDING) AS streak_id
  FROM lagged
),
ranked AS (
  SELECT
    *,
    SUM(held_seconds) OVER (
      PARTITION BY equipment_id, streak_id ORDER BY timestamp_utc
      ROWS UNBOUNDED PRECEDING
    ) AS streak_elapsed
  FROM grp
),
final AS (
  SELECT
    equipment_id,
    held_seconds,
    CASE WHEN raw_fault = 1 AND streak_elapsed >= {{CONFIRM_SECONDS}} THEN 1 ELSE 0 END AS confirmed
  FROM ranked
)
SELECT
  equipment_id,
  SUM(CASE WHEN confirmed = 1 THEN held_seconds ELSE 0.0 END) / 3600.0 AS fault_hours,
  SUM(held_seconds) / 3600.0 AS covered_hours,
  100.0 * SUM(CASE WHEN confirmed = 1 THEN held_seconds ELSE 0.0 END) / NULLIF(SUM(held_seconds), 0.0) AS fault_pct
FROM final
GROUP BY equipment_id;
```
{% endraw %}

### cw_opt_1.sql

`sql/fdd/postgres/rules/cw_opt_1.sql`

{% raw %}
```sql
-- PostgreSQL adaptation. Render numeric template parameters with render_rule.py.
-- Inputs must be scoped to one tenant/site and cadence; see README.md.
-- cw_opt_1.sql — Condenser water not optimized vs wet-bulb
WITH h AS (
  SELECT
    equipment_id,
    timestamp_utc,
    cw_supply_t,
    web_wb_t,
    pump_status,
    chiller_status,
    chw_flow,
    chw_pump_cmd,
    CASE
      WHEN pump_status IS NOT NULL THEN CASE WHEN pump_status > 0.05 THEN 1 ELSE 0 END
      WHEN chiller_status IS NOT NULL THEN CASE WHEN chiller_status > 0.05 THEN 1 ELSE 0 END
      WHEN chw_flow IS NOT NULL THEN CASE WHEN chw_flow > 1.0 THEN 1 ELSE 0 END
      WHEN chw_pump_cmd IS NOT NULL THEN CASE WHEN (CASE WHEN chw_pump_cmd > 1.0 THEN chw_pump_cmd / 100.0 ELSE chw_pump_cmd END) > 0.05 THEN 1 ELSE 0 END
      ELSE 0
    END AS proof_on
  FROM history
),
base AS (
  SELECT
    equipment_id,
    timestamp_utc,
    CAST(CASE
      WHEN COALESCE(proof_on, 0) = 0 THEN 0
      WHEN cw_supply_t IS NULL OR web_wb_t IS NULL THEN 0
      WHEN cw_supply_t < web_wb_t + {{CW_APPROACH}} - {{CW_SLACK}} THEN 1
      ELSE 0
    END AS INT) AS raw_fault
  FROM h
),
elapsed_hold AS (
  -- Forward sample-and-hold. A gap longer than MAX_GAP_HOURS is unknown:
  -- it is not fault time, not covered time, and it breaks confirmation.
  -- The last sample has no forward interval.
  SELECT
    stepped.*,
    CASE
      WHEN stepped.dt_seconds IS NULL
        OR stepped.dt_seconds <= 0.0
        OR stepped.dt_seconds > ({{MAX_GAP_HOURS}} * 3600.0)
      THEN 0.0
      ELSE stepped.dt_seconds
    END AS held_seconds,
    CASE
      WHEN stepped.dt_seconds > ({{MAX_GAP_HOURS}} * 3600.0) THEN 1
      ELSE 0
    END AS gap_after
  FROM (
    SELECT
      src.*,
      EXTRACT(EPOCH FROM (
        LEAD(src.timestamp_utc) OVER (
          PARTITION BY src.equipment_id ORDER BY src.timestamp_utc
        ) - src.timestamp_utc
      )) AS dt_seconds
    FROM base src
  ) stepped
),
lagged AS (
  SELECT
    *,
    CASE
      WHEN raw_fault = LAG(raw_fault) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc)
       AND COALESCE(LAG(gap_after) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc), 0) = 0
      THEN 0 ELSE 1
    END AS is_new_streak
  FROM elapsed_hold
),
grp AS (
  SELECT
    *,
    SUM(is_new_streak)
      OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS UNBOUNDED PRECEDING) AS streak_id
  FROM lagged
),
ranked AS (
  SELECT
    *,
    SUM(held_seconds) OVER (
      PARTITION BY equipment_id, streak_id ORDER BY timestamp_utc
      ROWS UNBOUNDED PRECEDING
    ) AS streak_elapsed
  FROM grp
),
final AS (
  SELECT
    equipment_id,
    held_seconds,
    CASE WHEN raw_fault = 1 AND streak_elapsed >= {{CONFIRM_SECONDS}} THEN 1 ELSE 0 END AS confirmed
  FROM ranked
)
SELECT
  equipment_id,
  SUM(CASE WHEN confirmed = 1 THEN held_seconds ELSE 0.0 END) / 3600.0 AS fault_hours,
  SUM(held_seconds) / 3600.0 AS covered_hours,
  100.0 * SUM(CASE WHEN confirmed = 1 THEN held_seconds ELSE 0.0 END) / NULLIF(SUM(held_seconds), 0.0) AS fault_pct
FROM final
GROUP BY equipment_id;
```
{% endraw %}

### dmp1_oa_damper_leak.sql

`sql/fdd/postgres/rules/dmp1_oa_damper_leak.sql`

{% raw %}
```sql
-- PostgreSQL adaptation. Render numeric template parameters with render_rule.py.
-- Inputs must be scoped to one tenant/site and cadence; see README.md.
-- dmp1_oa_damper_leak.sql — OA damper leakage
WITH h AS (
  SELECT
    equipment_id,
    timestamp_utc,
    oa_t, mat,
    CASE WHEN oa_damper_pct IS NULL THEN NULL WHEN oa_damper_pct > 1.0 THEN oa_damper_pct / 100.0 ELSE oa_damper_pct END AS oa_d,
    fan_cmd,
    fan_status,
    CASE
      WHEN fan_status IS NOT NULL THEN CASE WHEN fan_status > 0.05 THEN 1 ELSE 0 END
      WHEN fan_cmd IS NOT NULL THEN CASE WHEN (CASE WHEN fan_cmd > 1.0 THEN fan_cmd / 100.0 ELSE fan_cmd END) > 0.01 THEN 1 ELSE 0 END
      ELSE 1
    END AS fan_on

  FROM history
),
base AS (
  SELECT
    equipment_id,
    timestamp_utc,
    CAST(CASE
      WHEN COALESCE(fan_on, 1) = 0 THEN 0
      WHEN oa_d IS NULL OR oa_t IS NULL OR mat IS NULL THEN 0
      WHEN oa_d <= 0.05 AND ABS(mat - oa_t) < {{LEAK_DELTA}} THEN 1
      ELSE 0
    END AS INT) AS raw_fault
  FROM h
),
elapsed_hold AS (
  -- Forward sample-and-hold. A gap longer than MAX_GAP_HOURS is unknown:
  -- it is not fault time, not covered time, and it breaks confirmation.
  -- The last sample has no forward interval.
  SELECT
    stepped.*,
    CASE
      WHEN stepped.dt_seconds IS NULL
        OR stepped.dt_seconds <= 0.0
        OR stepped.dt_seconds > ({{MAX_GAP_HOURS}} * 3600.0)
      THEN 0.0
      ELSE stepped.dt_seconds
    END AS held_seconds,
    CASE
      WHEN stepped.dt_seconds > ({{MAX_GAP_HOURS}} * 3600.0) THEN 1
      ELSE 0
    END AS gap_after
  FROM (
    SELECT
      src.*,
      EXTRACT(EPOCH FROM (
        LEAD(src.timestamp_utc) OVER (
          PARTITION BY src.equipment_id ORDER BY src.timestamp_utc
        ) - src.timestamp_utc
      )) AS dt_seconds
    FROM base src
  ) stepped
),
lagged AS (
  SELECT
    *,
    CASE
      WHEN raw_fault = LAG(raw_fault) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc)
       AND COALESCE(LAG(gap_after) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc), 0) = 0
      THEN 0 ELSE 1
    END AS is_new_streak
  FROM elapsed_hold
),
grp AS (
  SELECT
    *,
    SUM(is_new_streak)
      OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS UNBOUNDED PRECEDING) AS streak_id
  FROM lagged
),
ranked AS (
  SELECT
    *,
    SUM(held_seconds) OVER (
      PARTITION BY equipment_id, streak_id ORDER BY timestamp_utc
      ROWS UNBOUNDED PRECEDING
    ) AS streak_elapsed
  FROM grp
),
final AS (
  SELECT
    equipment_id,
    held_seconds,
    CASE WHEN raw_fault = 1 AND streak_elapsed >= {{CONFIRM_SECONDS}} THEN 1 ELSE 0 END AS confirmed
  FROM ranked
)
SELECT
  equipment_id,
  SUM(CASE WHEN confirmed = 1 THEN held_seconds ELSE 0.0 END) / 3600.0 AS fault_hours,
  SUM(held_seconds) / 3600.0 AS covered_hours,
  100.0 * SUM(CASE WHEN confirmed = 1 THEN held_seconds ELSE 0.0 END) / NULLIF(SUM(held_seconds), 0.0) AS fault_pct
FROM final
GROUP BY equipment_id;
```
{% endraw %}

### econ1_stuck_closed.sql

`sql/fdd/postgres/rules/econ1_stuck_closed.sql`

{% raw %}
```sql
-- PostgreSQL adaptation. Render numeric template parameters with render_rule.py.
-- Inputs must be scoped to one tenant/site and cadence; see README.md.
-- econ1_stuck_closed.sql — ECON-1 economizer stuck closed
-- CAST DOUBLE + percent gate >= 1.5 on damper and fan_cmd (B100 0–100).
-- Pandas _fan is fan-cmd first (percent-normalized), then fan-status (> 0.5).
WITH base AS (
  SELECT
    equipment_id,
    timestamp_utc,
    CAST(CASE
      WHEN CASE
        WHEN fan_cmd IS NOT NULL THEN CASE
          WHEN (
            CASE
              WHEN CAST(fan_cmd AS DOUBLE PRECISION) >= 1.5
              THEN CAST(fan_cmd AS DOUBLE PRECISION) / 100.0
              ELSE CAST(fan_cmd AS DOUBLE PRECISION)
            END
          ) > 0.01 THEN 1
          ELSE 0
        END
        WHEN fan_status IS NOT NULL THEN CASE WHEN CAST(fan_status AS DOUBLE PRECISION) > 0.5 THEN 1 ELSE 0 END
        ELSE 0
      END = 0 THEN 0
      WHEN oa_damper_pct IS NOT NULL AND oa_t IS NOT NULL
       AND (
         CASE
           WHEN CAST(oa_damper_pct AS DOUBLE PRECISION) >= 1.5
           THEN CAST(oa_damper_pct AS DOUBLE PRECISION) / 100.0
           ELSE CAST(oa_damper_pct AS DOUBLE PRECISION)
         END
       ) < {{ECON1_DAMPER_MAX}}
       AND CAST(oa_t AS DOUBLE PRECISION) > {{ECON1_OAT_MIN}}
      THEN 1 ELSE 0 END AS INT) AS raw_fault
  FROM history
),
elapsed_hold AS (
  -- Forward sample-and-hold. A gap longer than MAX_GAP_HOURS is unknown:
  -- it is not fault time, not covered time, and it breaks confirmation.
  -- The last sample has no forward interval.
  SELECT
    stepped.*,
    CASE
      WHEN stepped.dt_seconds IS NULL
        OR stepped.dt_seconds <= 0.0
        OR stepped.dt_seconds > ({{MAX_GAP_HOURS}} * 3600.0)
      THEN 0.0
      ELSE stepped.dt_seconds
    END AS held_seconds,
    CASE
      WHEN stepped.dt_seconds > ({{MAX_GAP_HOURS}} * 3600.0) THEN 1
      ELSE 0
    END AS gap_after
  FROM (
    SELECT
      src.*,
      EXTRACT(EPOCH FROM (
        LEAD(src.timestamp_utc) OVER (
          PARTITION BY src.equipment_id ORDER BY src.timestamp_utc
        ) - src.timestamp_utc
      )) AS dt_seconds
    FROM base src
  ) stepped
),
lagged AS (
  SELECT
    *,
    CASE
      WHEN raw_fault = LAG(raw_fault) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc)
       AND COALESCE(LAG(gap_after) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc), 0) = 0
      THEN 0 ELSE 1
    END AS is_new_streak
  FROM elapsed_hold
),
grp AS (
  SELECT
    *,
    SUM(is_new_streak)
      OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS UNBOUNDED PRECEDING) AS streak_id
  FROM lagged
),
ranked AS (
  SELECT
    *,
    SUM(held_seconds) OVER (
      PARTITION BY equipment_id, streak_id ORDER BY timestamp_utc
      ROWS UNBOUNDED PRECEDING
    ) AS streak_elapsed
  FROM grp
),
final AS (
  SELECT
    equipment_id,
    held_seconds,
    CASE WHEN raw_fault = 1 AND streak_elapsed >= {{CONFIRM_SECONDS}} THEN 1 ELSE 0 END AS confirmed
  FROM ranked
)
SELECT
  equipment_id,
  SUM(CASE WHEN confirmed = 1 THEN held_seconds ELSE 0.0 END) / 3600.0 AS fault_hours,
  SUM(held_seconds) / 3600.0 AS covered_hours,
  100.0 * SUM(CASE WHEN confirmed = 1 THEN held_seconds ELSE 0.0 END) / NULLIF(SUM(held_seconds), 0.0) AS fault_pct
FROM final
GROUP BY equipment_id;
```
{% endraw %}

### econ3_mech_without_econ.sql

`sql/fdd/postgres/rules/econ3_mech_without_econ.sql`

{% raw %}
```sql
-- PostgreSQL adaptation. Render numeric template parameters with render_rule.py.
-- Inputs must be scoped to one tenant/site and cadence; see README.md.
-- econ3_mech_without_econ.sql — Mech cooling without integrated economizer
-- Web DB+DP: prefer equipment web_oa_* (pandas); else weather sidecar (OAT-METEO join).
-- Never substitute BAS oa_t.
WITH wx AS (
  SELECT
    timestamp_utc,
    MAX(web_oa_t) AS wx_web_oa_t,
    MAX(web_oa_dp) AS wx_web_oa_dp
  FROM weather
  GROUP BY timestamp_utc
),
h AS (
  SELECT
    h.equipment_id,
    h.timestamp_utc,
    COALESCE(h.web_oa_t, wx.wx_web_oa_t) AS web_oa_t,
    COALESCE(h.web_oa_dp, wx.wx_web_oa_dp) AS web_oa_dp,
    CASE WHEN h.oa_damper_pct IS NULL THEN NULL WHEN h.oa_damper_pct > 1.0 THEN h.oa_damper_pct / 100.0 ELSE h.oa_damper_pct END AS oa_d,
    CASE WHEN h.clg_valve_pct IS NULL THEN NULL WHEN h.clg_valve_pct > 1.0 THEN h.clg_valve_pct / 100.0 ELSE h.clg_valve_pct END AS clg,
    h.fan_cmd,
    h.fan_status,
    CASE
      WHEN h.fan_status IS NOT NULL THEN CASE WHEN h.fan_status > 0.05 THEN 1 ELSE 0 END
      WHEN h.fan_cmd IS NOT NULL THEN CASE WHEN (CASE WHEN h.fan_cmd > 1.0 THEN h.fan_cmd / 100.0 ELSE h.fan_cmd END) > 0.01 THEN 1 ELSE 0 END
      ELSE 1
    END AS fan_on
  FROM history h
  LEFT JOIN wx
    ON h.timestamp_utc = wx.timestamp_utc
),
base AS (
  SELECT
    equipment_id,
    timestamp_utc,
    CAST(CASE
      WHEN COALESCE(fan_on, 1) = 0 THEN 0
      WHEN web_oa_t IS NULL OR web_oa_dp IS NULL OR oa_d IS NULL OR clg IS NULL THEN 0
      WHEN web_oa_t >= {{ECON3_DB_MIN}} AND web_oa_t < {{ECON3_DB_MAX}} AND web_oa_dp < {{ECON3_DP_MAX}}
       AND clg > {{CLG_OPEN_MIN}} AND oa_d < {{ECON3_DAMPER_HI}} THEN 1
      ELSE 0
    END AS INT) AS raw_fault
  FROM h
),
elapsed_hold AS (
  -- Forward sample-and-hold. A gap longer than MAX_GAP_HOURS is unknown:
  -- it is not fault time, not covered time, and it breaks confirmation.
  -- The last sample has no forward interval.
  SELECT
    stepped.*,
    CASE
      WHEN stepped.dt_seconds IS NULL
        OR stepped.dt_seconds <= 0.0
        OR stepped.dt_seconds > ({{MAX_GAP_HOURS}} * 3600.0)
      THEN 0.0
      ELSE stepped.dt_seconds
    END AS held_seconds,
    CASE
      WHEN stepped.dt_seconds > ({{MAX_GAP_HOURS}} * 3600.0) THEN 1
      ELSE 0
    END AS gap_after
  FROM (
    SELECT
      src.*,
      EXTRACT(EPOCH FROM (
        LEAD(src.timestamp_utc) OVER (
          PARTITION BY src.equipment_id ORDER BY src.timestamp_utc
        ) - src.timestamp_utc
      )) AS dt_seconds
    FROM base src
  ) stepped
),
lagged AS (
  SELECT
    *,
    CASE
      WHEN raw_fault = LAG(raw_fault) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc)
       AND COALESCE(LAG(gap_after) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc), 0) = 0
      THEN 0 ELSE 1
    END AS is_new_streak
  FROM elapsed_hold
),
grp AS (
  SELECT
    *,
    SUM(is_new_streak)
      OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS UNBOUNDED PRECEDING) AS streak_id
  FROM lagged
),
ranked AS (
  SELECT
    *,
    SUM(held_seconds) OVER (
      PARTITION BY equipment_id, streak_id ORDER BY timestamp_utc
      ROWS UNBOUNDED PRECEDING
    ) AS streak_elapsed
  FROM grp
),
final AS (
  SELECT
    equipment_id,
    held_seconds,
    CASE WHEN raw_fault = 1 AND streak_elapsed >= {{CONFIRM_SECONDS}} THEN 1 ELSE 0 END AS confirmed
  FROM ranked
)
SELECT
  equipment_id,
  SUM(CASE WHEN confirmed = 1 THEN held_seconds ELSE 0.0 END) / 3600.0 AS fault_hours,
  SUM(held_seconds) / 3600.0 AS covered_hours,
  100.0 * SUM(CASE WHEN confirmed = 1 THEN held_seconds ELSE 0.0 END) / NULLIF(SUM(held_seconds), 0.0) AS fault_pct
FROM final
GROUP BY equipment_id;
```
{% endraw %}

### econ4_low_oa_frac.sql

`sql/fdd/postgres/rules/econ4_low_oa_frac.sql`

{% raw %}
```sql
-- PostgreSQL adaptation. Render numeric template parameters with render_rule.py.
-- Inputs must be scoped to one tenant/site and cadence; see README.md.
-- econ4_low_oa_frac.sql — ECON-4 low estimated OA fraction + confirm (600s)
WITH h AS (
  SELECT
    equipment_id,
    timestamp_utc,
    mat,
    rat,
    oa_t,
    COALESCE(CASE WHEN fan_cmd IS NULL THEN 0.0 WHEN fan_cmd > 1.0 THEN fan_cmd / 100.0 ELSE fan_cmd END, 0.0) AS fan,
    CASE
      WHEN fan_status IS NOT NULL THEN CASE WHEN fan_status > 0.05 THEN 1 ELSE 0 END
      WHEN fan_cmd IS NOT NULL THEN CASE WHEN (CASE WHEN fan_cmd > 1.0 THEN fan_cmd / 100.0 ELSE fan_cmd END) > 0.01 THEN 1 ELSE 0 END
      ELSE 1
    END AS fan_on

  FROM history
),
base AS (
  SELECT
    equipment_id,
    timestamp_utc,
    CAST(CASE
      WHEN COALESCE(fan_on, 1) = 0 THEN 0
      WHEN fan > 0.01 AND mat IS NOT NULL AND rat IS NOT NULL AND oa_t IS NOT NULL
       AND ABS(rat - oa_t) > {{OAT_RAT_DELTA_MIN}}
       AND ((mat - rat) / NULLIF(oa_t - rat, 0)) * 100.0 < {{OA_MIN_PCT}}
      THEN 1 ELSE 0 END AS INT) AS raw_fault
  FROM h
),
elapsed_hold AS (
  -- Forward sample-and-hold. A gap longer than MAX_GAP_HOURS is unknown:
  -- it is not fault time, not covered time, and it breaks confirmation.
  -- The last sample has no forward interval.
  SELECT
    stepped.*,
    CASE
      WHEN stepped.dt_seconds IS NULL
        OR stepped.dt_seconds <= 0.0
        OR stepped.dt_seconds > ({{MAX_GAP_HOURS}} * 3600.0)
      THEN 0.0
      ELSE stepped.dt_seconds
    END AS held_seconds,
    CASE
      WHEN stepped.dt_seconds > ({{MAX_GAP_HOURS}} * 3600.0) THEN 1
      ELSE 0
    END AS gap_after
  FROM (
    SELECT
      src.*,
      EXTRACT(EPOCH FROM (
        LEAD(src.timestamp_utc) OVER (
          PARTITION BY src.equipment_id ORDER BY src.timestamp_utc
        ) - src.timestamp_utc
      )) AS dt_seconds
    FROM base src
  ) stepped
),
lagged AS (
  SELECT
    *,
    CASE
      WHEN raw_fault = LAG(raw_fault) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc)
       AND COALESCE(LAG(gap_after) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc), 0) = 0
      THEN 0 ELSE 1
    END AS is_new_streak
  FROM elapsed_hold
),
grp AS (
  SELECT
    *,
    SUM(is_new_streak)
      OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS UNBOUNDED PRECEDING) AS streak_id
  FROM lagged
),
ranked AS (
  SELECT
    *,
    SUM(held_seconds) OVER (
      PARTITION BY equipment_id, streak_id ORDER BY timestamp_utc
      ROWS UNBOUNDED PRECEDING
    ) AS streak_elapsed
  FROM grp
),
final AS (
  SELECT
    equipment_id,
    held_seconds,
    CASE WHEN raw_fault = 1 AND streak_elapsed >= {{CONFIRM_SECONDS}} THEN 1 ELSE 0 END AS confirmed
  FROM ranked
)
SELECT
  equipment_id,
  SUM(CASE WHEN confirmed = 1 THEN held_seconds ELSE 0.0 END) / 3600.0 AS fault_hours,
  SUM(held_seconds) / 3600.0 AS covered_hours,
  100.0 * SUM(CASE WHEN confirmed = 1 THEN held_seconds ELSE 0.0 END) / NULLIF(SUM(held_seconds), 0.0) AS fault_pct
FROM final
GROUP BY equipment_id;
```
{% endraw %}

### econ5_preheat_over.sql

`sql/fdd/postgres/rules/econ5_preheat_over.sql`

{% raw %}
```sql
-- PostgreSQL adaptation. Render numeric template parameters with render_rule.py.
-- Inputs must be scoped to one tenant/site and cadence; see README.md.
-- econ5_preheat_over.sql — Preheat over-conditioning (matches vibe19 econ5)
-- Target = OAT when OAT > SAT SP; else SAT SP. Fault when preheat exceeds target by ΔT
-- while heating valve is open.
WITH h AS (
  SELECT
    equipment_id,
    timestamp_utc,
    preheat_leave_t, sat_sp, oa_t,
    CASE WHEN htg_valve_pct IS NULL THEN 0.0 WHEN htg_valve_pct > 1.0 THEN htg_valve_pct / 100.0 ELSE htg_valve_pct END AS htg,
    fan_cmd,
    fan_status,
    CASE
      WHEN fan_status IS NOT NULL THEN CASE WHEN fan_status > 0.05 THEN 1 ELSE 0 END
      WHEN fan_cmd IS NOT NULL THEN CASE WHEN (CASE WHEN fan_cmd > 1.0 THEN fan_cmd / 100.0 ELSE fan_cmd END) > 0.01 THEN 1 ELSE 0 END
      ELSE 1
    END AS fan_on

  FROM history
),
base AS (
  SELECT
    equipment_id,
    timestamp_utc,
    CAST(CASE
      WHEN COALESCE(fan_on, 1) = 0 THEN 0
      WHEN preheat_leave_t IS NULL OR sat_sp IS NULL OR oa_t IS NULL THEN 0
      WHEN htg > {{HTG_OPEN_MIN}} AND (
        (oa_t > sat_sp AND preheat_leave_t - oa_t > {{PREHEAT_OVER_F}})
        OR (oa_t < sat_sp AND preheat_leave_t - sat_sp > {{PREHEAT_OVER_F}})
      ) THEN 1
      ELSE 0
    END AS INT) AS raw_fault
  FROM h
),
elapsed_hold AS (
  -- Forward sample-and-hold. A gap longer than MAX_GAP_HOURS is unknown:
  -- it is not fault time, not covered time, and it breaks confirmation.
  -- The last sample has no forward interval.
  SELECT
    stepped.*,
    CASE
      WHEN stepped.dt_seconds IS NULL
        OR stepped.dt_seconds <= 0.0
        OR stepped.dt_seconds > ({{MAX_GAP_HOURS}} * 3600.0)
      THEN 0.0
      ELSE stepped.dt_seconds
    END AS held_seconds,
    CASE
      WHEN stepped.dt_seconds > ({{MAX_GAP_HOURS}} * 3600.0) THEN 1
      ELSE 0
    END AS gap_after
  FROM (
    SELECT
      src.*,
      EXTRACT(EPOCH FROM (
        LEAD(src.timestamp_utc) OVER (
          PARTITION BY src.equipment_id ORDER BY src.timestamp_utc
        ) - src.timestamp_utc
      )) AS dt_seconds
    FROM base src
  ) stepped
),
lagged AS (
  SELECT
    *,
    CASE
      WHEN raw_fault = LAG(raw_fault) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc)
       AND COALESCE(LAG(gap_after) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc), 0) = 0
      THEN 0 ELSE 1
    END AS is_new_streak
  FROM elapsed_hold
),
grp AS (
  SELECT
    *,
    SUM(is_new_streak)
      OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS UNBOUNDED PRECEDING) AS streak_id
  FROM lagged
),
ranked AS (
  SELECT
    *,
    SUM(held_seconds) OVER (
      PARTITION BY equipment_id, streak_id ORDER BY timestamp_utc
      ROWS UNBOUNDED PRECEDING
    ) AS streak_elapsed
  FROM grp
),
final AS (
  SELECT
    equipment_id,
    held_seconds,
    CASE WHEN raw_fault = 1 AND streak_elapsed >= {{CONFIRM_SECONDS}} THEN 1 ELSE 0 END AS confirmed
  FROM ranked
)
SELECT
  equipment_id,
  SUM(CASE WHEN confirmed = 1 THEN held_seconds ELSE 0.0 END) / 3600.0 AS fault_hours,
  SUM(held_seconds) / 3600.0 AS covered_hours,
  100.0 * SUM(CASE WHEN confirmed = 1 THEN held_seconds ELSE 0.0 END) / NULLIF(SUM(held_seconds), 0.0) AS fault_pct
FROM final
GROUP BY equipment_id;
```
{% endraw %}

### econ6_econ_freezing.sql

`sql/fdd/postgres/rules/econ6_econ_freezing.sql`

{% raw %}
```sql
-- PostgreSQL adaptation. Render numeric template parameters with render_rule.py.
-- Inputs must be scoped to one tenant/site and cadence; see README.md.
-- econ6_econ_freezing.sql — Economizing in freezing weather
-- Web dry-bulb: prefer equipment web_oa_t; else weather sidecar. Never BAS oa_t.
WITH wx AS (
  SELECT
    timestamp_utc,
    MAX(web_oa_t) AS wx_web_oa_t
  FROM weather
  GROUP BY timestamp_utc
),
h AS (
  SELECT
    h.equipment_id,
    h.timestamp_utc,
    COALESCE(h.web_oa_t, wx.wx_web_oa_t) AS web_oa_t,
    CASE WHEN h.oa_damper_pct IS NULL THEN NULL WHEN h.oa_damper_pct > 1.0 THEN h.oa_damper_pct / 100.0 ELSE h.oa_damper_pct END AS oa_d,
    h.fan_cmd,
    h.fan_status,
    CASE
      WHEN h.fan_status IS NOT NULL THEN CASE WHEN h.fan_status > 0.05 THEN 1 ELSE 0 END
      WHEN h.fan_cmd IS NOT NULL THEN CASE WHEN (CASE WHEN h.fan_cmd > 1.0 THEN h.fan_cmd / 100.0 ELSE h.fan_cmd END) > 0.01 THEN 1 ELSE 0 END
      ELSE 1
    END AS fan_on
  FROM history h
  LEFT JOIN wx
    ON h.timestamp_utc = wx.timestamp_utc
),
base AS (
  SELECT
    equipment_id,
    timestamp_utc,
    CAST(CASE
      WHEN COALESCE(fan_on, 1) = 0 THEN 0
      WHEN web_oa_t IS NULL OR oa_d IS NULL THEN 0
      WHEN web_oa_t < {{ECON6_OAT_MAX_F}} AND oa_d > {{ECON6_DAMPER_MAX}} THEN 1
      ELSE 0
    END AS INT) AS raw_fault
  FROM h
),
elapsed_hold AS (
  -- Forward sample-and-hold. A gap longer than MAX_GAP_HOURS is unknown:
  -- it is not fault time, not covered time, and it breaks confirmation.
  -- The last sample has no forward interval.
  SELECT
    stepped.*,
    CASE
      WHEN stepped.dt_seconds IS NULL
        OR stepped.dt_seconds <= 0.0
        OR stepped.dt_seconds > ({{MAX_GAP_HOURS}} * 3600.0)
      THEN 0.0
      ELSE stepped.dt_seconds
    END AS held_seconds,
    CASE
      WHEN stepped.dt_seconds > ({{MAX_GAP_HOURS}} * 3600.0) THEN 1
      ELSE 0
    END AS gap_after
  FROM (
    SELECT
      src.*,
      EXTRACT(EPOCH FROM (
        LEAD(src.timestamp_utc) OVER (
          PARTITION BY src.equipment_id ORDER BY src.timestamp_utc
        ) - src.timestamp_utc
      )) AS dt_seconds
    FROM base src
  ) stepped
),
lagged AS (
  SELECT
    *,
    CASE
      WHEN raw_fault = LAG(raw_fault) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc)
       AND COALESCE(LAG(gap_after) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc), 0) = 0
      THEN 0 ELSE 1
    END AS is_new_streak
  FROM elapsed_hold
),
grp AS (
  SELECT
    *,
    SUM(is_new_streak)
      OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS UNBOUNDED PRECEDING) AS streak_id
  FROM lagged
),
ranked AS (
  SELECT
    *,
    SUM(held_seconds) OVER (
      PARTITION BY equipment_id, streak_id ORDER BY timestamp_utc
      ROWS UNBOUNDED PRECEDING
    ) AS streak_elapsed
  FROM grp
),
final AS (
  SELECT
    equipment_id,
    held_seconds,
    CASE WHEN raw_fault = 1 AND streak_elapsed >= {{CONFIRM_SECONDS}} THEN 1 ELSE 0 END AS confirmed
  FROM ranked
)
SELECT
  equipment_id,
  SUM(CASE WHEN confirmed = 1 THEN held_seconds ELSE 0.0 END) / 3600.0 AS fault_hours,
  SUM(held_seconds) / 3600.0 AS covered_hours,
  100.0 * SUM(CASE WHEN confirmed = 1 THEN held_seconds ELSE 0.0 END) / NULLIF(SUM(held_seconds), 0.0) AS fault_pct
FROM final
GROUP BY equipment_id;
```
{% endraw %}

### econ7_ok_not_economizing.sql

`sql/fdd/postgres/rules/econ7_ok_not_economizing.sql`

{% raw %}
```sql
-- PostgreSQL adaptation. Render numeric template parameters with render_rule.py.
-- Inputs must be scoped to one tenant/site and cadence; see README.md.
-- econ7_ok_not_economizing.sql — Economizer OK but not economizing
-- Web DB+DP: prefer equipment web_oa_*; else weather sidecar. Never BAS oa_t.
WITH wx AS (
  SELECT
    timestamp_utc,
    MAX(web_oa_t) AS wx_web_oa_t,
    MAX(web_oa_dp) AS wx_web_oa_dp
  FROM weather
  GROUP BY timestamp_utc
),
h AS (
  SELECT
    h.equipment_id,
    h.timestamp_utc,
    COALESCE(h.web_oa_t, wx.wx_web_oa_t) AS web_oa_t,
    COALESCE(h.web_oa_dp, wx.wx_web_oa_dp) AS web_oa_dp,
    CASE WHEN h.oa_damper_pct IS NULL THEN NULL WHEN h.oa_damper_pct > 1.0 THEN h.oa_damper_pct / 100.0 ELSE h.oa_damper_pct END AS oa_d,
    CASE WHEN h.clg_valve_pct IS NULL THEN NULL WHEN h.clg_valve_pct > 1.0 THEN h.clg_valve_pct / 100.0 ELSE h.clg_valve_pct END AS clg,
    h.fan_cmd,
    h.fan_status,
    CASE
      WHEN h.fan_status IS NOT NULL THEN CASE WHEN h.fan_status > 0.05 THEN 1 ELSE 0 END
      WHEN h.fan_cmd IS NOT NULL THEN CASE WHEN (CASE WHEN h.fan_cmd > 1.0 THEN h.fan_cmd / 100.0 ELSE h.fan_cmd END) > 0.01 THEN 1 ELSE 0 END
      ELSE 1
    END AS fan_on
  FROM history h
  LEFT JOIN wx
    ON h.timestamp_utc = wx.timestamp_utc
),
base AS (
  SELECT
    equipment_id,
    timestamp_utc,
    CAST(CASE
      WHEN COALESCE(fan_on, 1) = 0 THEN 0
      WHEN web_oa_t IS NULL OR web_oa_dp IS NULL OR oa_d IS NULL OR clg IS NULL THEN 0
      WHEN web_oa_t >= {{ECON7_DB_MIN}} AND web_oa_t < {{ECON7_DB_MAX}} AND web_oa_dp < {{ECON7_DP_MAX}}
       AND clg > {{CLG_OPEN_MIN}} AND oa_d < {{ECON7_DAMPER_MIN}} THEN 1
      ELSE 0
    END AS INT) AS raw_fault
  FROM h
),
elapsed_hold AS (
  -- Forward sample-and-hold. A gap longer than MAX_GAP_HOURS is unknown:
  -- it is not fault time, not covered time, and it breaks confirmation.
  -- The last sample has no forward interval.
  SELECT
    stepped.*,
    CASE
      WHEN stepped.dt_seconds IS NULL
        OR stepped.dt_seconds <= 0.0
        OR stepped.dt_seconds > ({{MAX_GAP_HOURS}} * 3600.0)
      THEN 0.0
      ELSE stepped.dt_seconds
    END AS held_seconds,
    CASE
      WHEN stepped.dt_seconds > ({{MAX_GAP_HOURS}} * 3600.0) THEN 1
      ELSE 0
    END AS gap_after
  FROM (
    SELECT
      src.*,
      EXTRACT(EPOCH FROM (
        LEAD(src.timestamp_utc) OVER (
          PARTITION BY src.equipment_id ORDER BY src.timestamp_utc
        ) - src.timestamp_utc
      )) AS dt_seconds
    FROM base src
  ) stepped
),
lagged AS (
  SELECT
    *,
    CASE
      WHEN raw_fault = LAG(raw_fault) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc)
       AND COALESCE(LAG(gap_after) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc), 0) = 0
      THEN 0 ELSE 1
    END AS is_new_streak
  FROM elapsed_hold
),
grp AS (
  SELECT
    *,
    SUM(is_new_streak)
      OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS UNBOUNDED PRECEDING) AS streak_id
  FROM lagged
),
ranked AS (
  SELECT
    *,
    SUM(held_seconds) OVER (
      PARTITION BY equipment_id, streak_id ORDER BY timestamp_utc
      ROWS UNBOUNDED PRECEDING
    ) AS streak_elapsed
  FROM grp
),
final AS (
  SELECT
    equipment_id,
    held_seconds,
    CASE WHEN raw_fault = 1 AND streak_elapsed >= {{CONFIRM_SECONDS}} THEN 1 ELSE 0 END AS confirmed
  FROM ranked
)
SELECT
  equipment_id,
  SUM(CASE WHEN confirmed = 1 THEN held_seconds ELSE 0.0 END) / 3600.0 AS fault_hours,
  SUM(held_seconds) / 3600.0 AS covered_hours,
  100.0 * SUM(CASE WHEN confirmed = 1 THEN held_seconds ELSE 0.0 END) / NULLIF(SUM(held_seconds), 0.0) AS fault_pct
FROM final
GROUP BY equipment_id;
```
{% endraw %}

### economizer_fault.sql

`sql/fdd/postgres/rules/economizer_fault.sql`

{% raw %}
```sql
-- PostgreSQL adaptation. Render numeric template parameters with render_rule.py.
-- Inputs must be scoped to one tenant/site and cadence; see README.md.
-- economizer_fault.sql — ECON-2 economizing when outdoor unfavorable + confirm
-- CAST DOUBLE + percent gate >= 1.5 (not > 1.0) so Utf8/int 0–100 (B100 min OA 20)
-- becomes 0.20 and does not fire vs ECON2_DAMPER 0.42. Fraction 0–1 stays 0–1.
-- Pandas econ2 has no fan gate.
WITH base AS (
  SELECT
    equipment_id,
    timestamp_utc,
    CAST(CASE
      WHEN oa_t IS NOT NULL AND oa_damper_pct IS NOT NULL
       AND CAST(oa_t AS DOUBLE PRECISION) > {{ECON2_OAT_HI}}
       AND (
         CASE
           WHEN CAST(oa_damper_pct AS DOUBLE PRECISION) >= 1.5
           THEN CAST(oa_damper_pct AS DOUBLE PRECISION) / 100.0
           ELSE CAST(oa_damper_pct AS DOUBLE PRECISION)
         END
       ) > {{ECON2_DAMPER}}
      THEN 1 ELSE 0 END AS INT) AS raw_fault
  FROM history
),
elapsed_hold AS (
  -- Forward sample-and-hold. A gap longer than MAX_GAP_HOURS is unknown:
  -- it is not fault time, not covered time, and it breaks confirmation.
  -- The last sample has no forward interval.
  SELECT
    stepped.*,
    CASE
      WHEN stepped.dt_seconds IS NULL
        OR stepped.dt_seconds <= 0.0
        OR stepped.dt_seconds > ({{MAX_GAP_HOURS}} * 3600.0)
      THEN 0.0
      ELSE stepped.dt_seconds
    END AS held_seconds,
    CASE
      WHEN stepped.dt_seconds > ({{MAX_GAP_HOURS}} * 3600.0) THEN 1
      ELSE 0
    END AS gap_after
  FROM (
    SELECT
      src.*,
      EXTRACT(EPOCH FROM (
        LEAD(src.timestamp_utc) OVER (
          PARTITION BY src.equipment_id ORDER BY src.timestamp_utc
        ) - src.timestamp_utc
      )) AS dt_seconds
    FROM base src
  ) stepped
),
lagged AS (
  SELECT
    *,
    CASE
      WHEN raw_fault = LAG(raw_fault) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc)
       AND COALESCE(LAG(gap_after) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc), 0) = 0
      THEN 0 ELSE 1
    END AS is_new_streak
  FROM elapsed_hold
),
grp AS (
  SELECT
    *,
    SUM(is_new_streak)
      OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS UNBOUNDED PRECEDING) AS streak_id
  FROM lagged
),
ranked AS (
  SELECT
    *,
    SUM(held_seconds) OVER (
      PARTITION BY equipment_id, streak_id ORDER BY timestamp_utc
      ROWS UNBOUNDED PRECEDING
    ) AS streak_elapsed
  FROM grp
),
final AS (
  SELECT
    equipment_id,
    held_seconds,
    CASE WHEN raw_fault = 1 AND streak_elapsed >= {{CONFIRM_SECONDS}} THEN 1 ELSE 0 END AS confirmed
  FROM ranked
)
SELECT
  equipment_id,
  SUM(CASE WHEN confirmed = 1 THEN held_seconds ELSE 0.0 END) / 3600.0 AS fault_hours,
  SUM(held_seconds) / 3600.0 AS covered_hours,
  100.0 * SUM(CASE WHEN confirmed = 1 THEN held_seconds ELSE 0.0 END) / NULLIF(SUM(held_seconds), 0.0) AS fault_pct
FROM final
GROUP BY equipment_id;
```
{% endraw %}

### fan_runtime_hours.sql

`sql/fdd/postgres/rules/fan_runtime_hours.sql`

{% raw %}
```sql
-- PostgreSQL adaptation. Render numeric template parameters with render_rule.py.
-- Inputs must be scoped to one tenant/site and cadence; see README.md.
-- fan_runtime_hours.sql
-- Fan runtime integrates the forward delta while fan_cmd > 0.05.
-- A gap longer than MAX_GAP_HOURS is unknown and is omitted from both totals.
-- The last sample does not invent a trailing interval.

WITH ordered AS (
  SELECT
    equipment_id,
    timestamp_utc,
    CASE WHEN fan_cmd IS NULL THEN NULL WHEN fan_cmd > 1.0 THEN fan_cmd / 100.0 ELSE fan_cmd END AS fan_cmd,
    EXTRACT(EPOCH FROM (
      LEAD(timestamp_utc) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc)
      - timestamp_utc
    )) AS dt_seconds
  FROM history
),
held AS (
  SELECT
    equipment_id,
    fan_cmd,
    CASE
      WHEN dt_seconds IS NULL OR dt_seconds <= 0.0 OR dt_seconds > ({{MAX_GAP_HOURS}} * 3600.0)
      THEN 0.0
      ELSE dt_seconds
    END AS held_seconds
  FROM ordered
)
SELECT
  equipment_id,
  SUM(CASE WHEN fan_cmd > 0.05 THEN held_seconds ELSE 0.0 END) / 3600.0 AS fan_runtime_hours,
  SUM(CASE WHEN fan_cmd IS NOT NULL THEN held_seconds ELSE 0.0 END) / 3600.0 AS total_hours
FROM held
GROUP BY equipment_id;
```
{% endraw %}

### fault_elapsed_hours.sql

`sql/fdd/postgres/rules/fault_elapsed_hours.sql`

{% raw %}
```sql
-- PostgreSQL adaptation. Render numeric template parameters with render_rule.py.
-- Inputs must be scoped to one tenant/site and cadence; see README.md.
-- fault_elapsed_hours.sql — comfort fault elapsed rollup
-- Out-of-band zone temperature holds forward until the next sample.
-- Gaps longer than MAX_GAP_HOURS are unknown (not fault, not covered).
WITH ordered AS (
  SELECT
    equipment_id,
    zone_t,
    EXTRACT(EPOCH FROM (
      LEAD(timestamp_utc) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc)
      - timestamp_utc
    )) AS dt_seconds
  FROM history
  WHERE zone_t IS NOT NULL
),
held AS (
  SELECT
    equipment_id,
    zone_t,
    CASE
      WHEN dt_seconds IS NULL OR dt_seconds <= 0.0 OR dt_seconds > ({{MAX_GAP_HOURS}} * 3600.0)
      THEN 0.0
      ELSE dt_seconds
    END AS held_seconds
  FROM ordered
)
SELECT
  equipment_id,
  SUM(CASE WHEN zone_t < 68.0 OR zone_t > 76.0 THEN 1 ELSE 0 END) AS fault_samples,
  SUM(CASE
    WHEN zone_t < {{ZONE_T_LO}} OR zone_t > {{ZONE_T_HI}} THEN held_seconds
    ELSE 0.0
  END) / 3600.0 AS fault_hours,
  SUM(held_seconds) / 3600.0 AS covered_hours,
  100.0 * SUM(CASE
    WHEN zone_t < {{ZONE_T_LO}} OR zone_t > {{ZONE_T_HI}} THEN held_seconds
    ELSE 0.0
  END) / NULLIF(SUM(held_seconds), 0.0) AS fault_pct
FROM held
GROUP BY equipment_id;
```
{% endraw %}

### fc10_mat_oa_clg.sql

`sql/fdd/postgres/rules/fc10_mat_oa_clg.sql`

{% raw %}
```sql
-- PostgreSQL adaptation. Render numeric template parameters with render_rule.py.
-- Inputs must be scoped to one tenant/site and cadence; see README.md.
-- fc10_mat_oa_clg.sql — FC10 MAT-OAT delta while cooling + economizing + confirm
WITH h AS (
  SELECT
    equipment_id,
    timestamp_utc,
    mat,
    oa_t,
    COALESCE(CASE WHEN oa_damper_pct IS NULL THEN NULL WHEN oa_damper_pct > 1.0 THEN oa_damper_pct / 100.0 ELSE oa_damper_pct END, 0.0) AS oa_damper_pct,
    COALESCE(CASE WHEN clg_valve_pct IS NULL THEN NULL WHEN clg_valve_pct > 1.0 THEN clg_valve_pct / 100.0 ELSE clg_valve_pct END, 0.0) AS clg_valve_pct,
    fan_cmd,
    fan_status,
        CASE
      WHEN {{REQUIRE_OPERATIONAL_GATE}} < 0.5 THEN 1
      WHEN fan_status IS NOT NULL THEN CASE WHEN fan_status > 0.05 THEN 1 ELSE 0 END
      WHEN fan_cmd IS NOT NULL THEN CASE WHEN (CASE WHEN fan_cmd > 1.0 THEN fan_cmd / 100.0 ELSE fan_cmd END) > {{FAN_ON_MIN}} THEN 1 ELSE 0 END
      ELSE 1
    END AS fan_on

  FROM history
),
base AS (
  SELECT
    equipment_id,
    timestamp_utc,
    CAST(CASE
      WHEN COALESCE(fan_on, 1) = 0 THEN 0
      WHEN COALESCE(mode_stable, 1) = 0 THEN 0
      WHEN mat IS NOT NULL AND oa_t IS NOT NULL
       AND clg_valve_pct > {{CLG_ON_MIN}} AND oa_damper_pct > {{ECON_FULL_OPEN}}
       AND ABS(mat - oa_t) > SQRT(2.0 * {{EPS_MAT}} * {{EPS_MAT}})
      THEN 1 ELSE 0 END AS INT) AS raw_fault
  FROM (
  SELECT h.*,
    CASE
      WHEN COALESCE(fan_on, 1) = 0 THEN 0
      WHEN SUM(CASE WHEN COALESCE(fan_on, 1) = 0 THEN 1 ELSE 0 END) OVER (
        PARTITION BY equipment_id ORDER BY timestamp_utc
        ROWS BETWEEN {{MODE_DELAY_ROWS_PRECEDING}} PRECEDING AND CURRENT ROW
      ) = 0 THEN 1
      ELSE 0
    END AS mode_stable
  FROM h
) h
),
elapsed_hold AS (
  -- Forward sample-and-hold. A gap longer than MAX_GAP_HOURS is unknown:
  -- it is not fault time, not covered time, and it breaks confirmation.
  -- The last sample has no forward interval.
  SELECT
    stepped.*,
    CASE
      WHEN stepped.dt_seconds IS NULL
        OR stepped.dt_seconds <= 0.0
        OR stepped.dt_seconds > ({{MAX_GAP_HOURS}} * 3600.0)
      THEN 0.0
      ELSE stepped.dt_seconds
    END AS held_seconds,
    CASE
      WHEN stepped.dt_seconds > ({{MAX_GAP_HOURS}} * 3600.0) THEN 1
      ELSE 0
    END AS gap_after
  FROM (
    SELECT
      src.*,
      EXTRACT(EPOCH FROM (
        LEAD(src.timestamp_utc) OVER (
          PARTITION BY src.equipment_id ORDER BY src.timestamp_utc
        ) - src.timestamp_utc
      )) AS dt_seconds
    FROM base src
  ) stepped
),
lagged AS (
  SELECT
    *,
    CASE
      WHEN raw_fault = LAG(raw_fault) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc)
       AND COALESCE(LAG(gap_after) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc), 0) = 0
      THEN 0 ELSE 1
    END AS is_new_streak
  FROM elapsed_hold
),
grp AS (
  SELECT
    *,
    SUM(is_new_streak)
      OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS UNBOUNDED PRECEDING) AS streak_id
  FROM lagged
),
ranked AS (
  SELECT
    *,
    SUM(held_seconds) OVER (
      PARTITION BY equipment_id, streak_id ORDER BY timestamp_utc
      ROWS UNBOUNDED PRECEDING
    ) AS streak_elapsed
  FROM grp
),
final AS (
  SELECT
    equipment_id,
    held_seconds,
    CASE WHEN raw_fault = 1 AND streak_elapsed >= {{CONFIRM_SECONDS}} THEN 1 ELSE 0 END AS confirmed
  FROM ranked
)
, cov AS (
  SELECT equipment_id,
    100.0 * AVG(CAST(COALESCE(fan_on, 1) AS DOUBLE PRECISION)) AS cov_pct
  FROM h
  GROUP BY equipment_id
)
SELECT
  f.equipment_id,
  CASE
    WHEN {{REQUIRE_OPERATIONAL_GATE}} < 0.5 THEN SUM(CASE WHEN f.confirmed = 1 THEN f.held_seconds ELSE 0.0 END) / 3600.0
    WHEN MAX(c.cov_pct) < {{MINIMUM_ACTIVE_COVERAGE_PCT}} THEN 0.0
    ELSE SUM(CASE WHEN f.confirmed = 1 THEN f.held_seconds ELSE 0.0 END) / 3600.0
  END AS fault_hours,
  SUM(f.held_seconds) / 3600.0 AS covered_hours,
  CASE
    WHEN {{REQUIRE_OPERATIONAL_GATE}} < 0.5 THEN 100.0 * SUM(CASE WHEN f.confirmed = 1 THEN f.held_seconds ELSE 0.0 END) / NULLIF(SUM(f.held_seconds), 0.0)
    WHEN MAX(c.cov_pct) < {{MINIMUM_ACTIVE_COVERAGE_PCT}} THEN 0.0
    ELSE 100.0 * SUM(CASE WHEN f.confirmed = 1 THEN f.held_seconds ELSE 0.0 END) / NULLIF(SUM(f.held_seconds), 0.0)
  END AS fault_pct
FROM final f
LEFT JOIN cov c ON f.equipment_id = c.equipment_id
GROUP BY f.equipment_id;
```
{% endraw %}

### fc11_oa_sat_sp_clg.sql

`sql/fdd/postgres/rules/fc11_oa_sat_sp_clg.sql`

{% raw %}
```sql
-- PostgreSQL adaptation. Render numeric template parameters with render_rule.py.
-- Inputs must be scoped to one tenant/site and cadence; see README.md.
-- fc11_oa_sat_sp_clg.sql — FC11 OAT low vs SAT SP while cooling + economizing + confirm
WITH h AS (
  SELECT
    equipment_id,
    timestamp_utc,
    oa_t,
    sat_sp,
    COALESCE(CASE WHEN oa_damper_pct IS NULL THEN NULL WHEN oa_damper_pct > 1.0 THEN oa_damper_pct / 100.0 ELSE oa_damper_pct END, 0.0) AS oa_damper_pct,
    COALESCE(CASE WHEN clg_valve_pct IS NULL THEN NULL WHEN clg_valve_pct > 1.0 THEN clg_valve_pct / 100.0 ELSE clg_valve_pct END, 0.0) AS clg_valve_pct,
    fan_cmd,
    fan_status,
        CASE
      WHEN {{REQUIRE_OPERATIONAL_GATE}} < 0.5 THEN 1
      WHEN fan_status IS NOT NULL THEN CASE WHEN fan_status > 0.05 THEN 1 ELSE 0 END
      WHEN fan_cmd IS NOT NULL THEN CASE WHEN (CASE WHEN fan_cmd > 1.0 THEN fan_cmd / 100.0 ELSE fan_cmd END) > {{FAN_ON_MIN}} THEN 1 ELSE 0 END
      ELSE 1
    END AS fan_on

  FROM history
),
base AS (
  SELECT
    equipment_id,
    timestamp_utc,
    CAST(CASE
      WHEN COALESCE(fan_on, 1) = 0 THEN 0
      WHEN COALESCE(mode_stable, 1) = 0 THEN 0
      WHEN oa_t IS NOT NULL AND sat_sp IS NOT NULL
       AND clg_valve_pct > {{CLG_ON_MIN}} AND oa_damper_pct > {{ECON_FULL_OPEN}}
       AND (oa_t + {{EPS_MAT}}) < (sat_sp - {{DELTA_SUPPLY_FAN}} - {{EPS_MAT}})
      THEN 1 ELSE 0 END AS INT) AS raw_fault
  FROM (
  SELECT h.*,
    CASE
      WHEN COALESCE(fan_on, 1) = 0 THEN 0
      WHEN SUM(CASE WHEN COALESCE(fan_on, 1) = 0 THEN 1 ELSE 0 END) OVER (
        PARTITION BY equipment_id ORDER BY timestamp_utc
        ROWS BETWEEN {{MODE_DELAY_ROWS_PRECEDING}} PRECEDING AND CURRENT ROW
      ) = 0 THEN 1
      ELSE 0
    END AS mode_stable
  FROM h
) h
),
elapsed_hold AS (
  -- Forward sample-and-hold. A gap longer than MAX_GAP_HOURS is unknown:
  -- it is not fault time, not covered time, and it breaks confirmation.
  -- The last sample has no forward interval.
  SELECT
    stepped.*,
    CASE
      WHEN stepped.dt_seconds IS NULL
        OR stepped.dt_seconds <= 0.0
        OR stepped.dt_seconds > ({{MAX_GAP_HOURS}} * 3600.0)
      THEN 0.0
      ELSE stepped.dt_seconds
    END AS held_seconds,
    CASE
      WHEN stepped.dt_seconds > ({{MAX_GAP_HOURS}} * 3600.0) THEN 1
      ELSE 0
    END AS gap_after
  FROM (
    SELECT
      src.*,
      EXTRACT(EPOCH FROM (
        LEAD(src.timestamp_utc) OVER (
          PARTITION BY src.equipment_id ORDER BY src.timestamp_utc
        ) - src.timestamp_utc
      )) AS dt_seconds
    FROM base src
  ) stepped
),
lagged AS (
  SELECT
    *,
    CASE
      WHEN raw_fault = LAG(raw_fault) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc)
       AND COALESCE(LAG(gap_after) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc), 0) = 0
      THEN 0 ELSE 1
    END AS is_new_streak
  FROM elapsed_hold
),
grp AS (
  SELECT
    *,
    SUM(is_new_streak)
      OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS UNBOUNDED PRECEDING) AS streak_id
  FROM lagged
),
ranked AS (
  SELECT
    *,
    SUM(held_seconds) OVER (
      PARTITION BY equipment_id, streak_id ORDER BY timestamp_utc
      ROWS UNBOUNDED PRECEDING
    ) AS streak_elapsed
  FROM grp
),
final AS (
  SELECT
    equipment_id,
    held_seconds,
    CASE WHEN raw_fault = 1 AND streak_elapsed >= {{CONFIRM_SECONDS}} THEN 1 ELSE 0 END AS confirmed
  FROM ranked
)
, cov AS (
  SELECT equipment_id,
    100.0 * AVG(CAST(COALESCE(fan_on, 1) AS DOUBLE PRECISION)) AS cov_pct
  FROM h
  GROUP BY equipment_id
)
SELECT
  f.equipment_id,
  CASE
    WHEN {{REQUIRE_OPERATIONAL_GATE}} < 0.5 THEN SUM(CASE WHEN f.confirmed = 1 THEN f.held_seconds ELSE 0.0 END) / 3600.0
    WHEN MAX(c.cov_pct) < {{MINIMUM_ACTIVE_COVERAGE_PCT}} THEN 0.0
    ELSE SUM(CASE WHEN f.confirmed = 1 THEN f.held_seconds ELSE 0.0 END) / 3600.0
  END AS fault_hours,
  SUM(f.held_seconds) / 3600.0 AS covered_hours,
  CASE
    WHEN {{REQUIRE_OPERATIONAL_GATE}} < 0.5 THEN 100.0 * SUM(CASE WHEN f.confirmed = 1 THEN f.held_seconds ELSE 0.0 END) / NULLIF(SUM(f.held_seconds), 0.0)
    WHEN MAX(c.cov_pct) < {{MINIMUM_ACTIVE_COVERAGE_PCT}} THEN 0.0
    ELSE 100.0 * SUM(CASE WHEN f.confirmed = 1 THEN f.held_seconds ELSE 0.0 END) / NULLIF(SUM(f.held_seconds), 0.0)
  END AS fault_pct
FROM final f
LEFT JOIN cov c ON f.equipment_id = c.equipment_id
GROUP BY f.equipment_id;
```
{% endraw %}

### fc12_sat_mat_clg.sql

`sql/fdd/postgres/rules/fc12_sat_mat_clg.sql`

{% raw %}
```sql
-- PostgreSQL adaptation. Render numeric template parameters with render_rule.py.
-- Inputs must be scoped to one tenant/site and cadence; see README.md.
-- fc12_sat_mat_clg.sql — FC12 SAT above MAT while cooling + confirm
WITH h AS (
  SELECT
    equipment_id,
    timestamp_utc,
    sat,
    mat,
    COALESCE(CASE WHEN oa_damper_pct IS NULL THEN NULL WHEN oa_damper_pct > 1.0 THEN oa_damper_pct / 100.0 ELSE oa_damper_pct END, 0.0) AS oa_damper_pct,
    COALESCE(CASE WHEN clg_valve_pct IS NULL THEN NULL WHEN clg_valve_pct > 1.0 THEN clg_valve_pct / 100.0 ELSE clg_valve_pct END, 0.0) AS clg_valve_pct,
    fan_cmd,
    fan_status,
        CASE
      WHEN {{REQUIRE_OPERATIONAL_GATE}} < 0.5 THEN 1
      WHEN fan_status IS NOT NULL THEN CASE WHEN fan_status > 0.05 THEN 1 ELSE 0 END
      WHEN fan_cmd IS NOT NULL THEN CASE WHEN (CASE WHEN fan_cmd > 1.0 THEN fan_cmd / 100.0 ELSE fan_cmd END) > {{FAN_ON_MIN}} THEN 1 ELSE 0 END
      ELSE 1
    END AS fan_on

  FROM history
),
base AS (
  SELECT
    equipment_id,
    timestamp_utc,
    CAST(CASE
      WHEN COALESCE(fan_on, 1) = 0 THEN 0
      WHEN COALESCE(mode_stable, 1) = 0 THEN 0
      WHEN sat IS NOT NULL AND mat IS NOT NULL AND clg_valve_pct > {{CLG_ON_MIN}}
       AND (sat - {{MIX_TOL}} - {{DELTA_SUPPLY_FAN}}) > (mat + {{MIX_TOL}})
       AND (oa_damper_pct <= {{ECON_MIN_POS}} OR oa_damper_pct > {{ECON_FULL_OPEN}})
      THEN 1 ELSE 0 END AS INT) AS raw_fault
  FROM (
  SELECT h.*,
    CASE
      WHEN COALESCE(fan_on, 1) = 0 THEN 0
      WHEN SUM(CASE WHEN COALESCE(fan_on, 1) = 0 THEN 1 ELSE 0 END) OVER (
        PARTITION BY equipment_id ORDER BY timestamp_utc
        ROWS BETWEEN {{MODE_DELAY_ROWS_PRECEDING}} PRECEDING AND CURRENT ROW
      ) = 0 THEN 1
      ELSE 0
    END AS mode_stable
  FROM h
) h
),
elapsed_hold AS (
  -- Forward sample-and-hold. A gap longer than MAX_GAP_HOURS is unknown:
  -- it is not fault time, not covered time, and it breaks confirmation.
  -- The last sample has no forward interval.
  SELECT
    stepped.*,
    CASE
      WHEN stepped.dt_seconds IS NULL
        OR stepped.dt_seconds <= 0.0
        OR stepped.dt_seconds > ({{MAX_GAP_HOURS}} * 3600.0)
      THEN 0.0
      ELSE stepped.dt_seconds
    END AS held_seconds,
    CASE
      WHEN stepped.dt_seconds > ({{MAX_GAP_HOURS}} * 3600.0) THEN 1
      ELSE 0
    END AS gap_after
  FROM (
    SELECT
      src.*,
      EXTRACT(EPOCH FROM (
        LEAD(src.timestamp_utc) OVER (
          PARTITION BY src.equipment_id ORDER BY src.timestamp_utc
        ) - src.timestamp_utc
      )) AS dt_seconds
    FROM base src
  ) stepped
),
lagged AS (
  SELECT
    *,
    CASE
      WHEN raw_fault = LAG(raw_fault) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc)
       AND COALESCE(LAG(gap_after) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc), 0) = 0
      THEN 0 ELSE 1
    END AS is_new_streak
  FROM elapsed_hold
),
grp AS (
  SELECT
    *,
    SUM(is_new_streak)
      OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS UNBOUNDED PRECEDING) AS streak_id
  FROM lagged
),
ranked AS (
  SELECT
    *,
    SUM(held_seconds) OVER (
      PARTITION BY equipment_id, streak_id ORDER BY timestamp_utc
      ROWS UNBOUNDED PRECEDING
    ) AS streak_elapsed
  FROM grp
),
final AS (
  SELECT
    equipment_id,
    held_seconds,
    CASE WHEN raw_fault = 1 AND streak_elapsed >= {{CONFIRM_SECONDS}} THEN 1 ELSE 0 END AS confirmed
  FROM ranked
)
, cov AS (
  SELECT equipment_id,
    100.0 * AVG(CAST(COALESCE(fan_on, 1) AS DOUBLE PRECISION)) AS cov_pct
  FROM h
  GROUP BY equipment_id
)
SELECT
  f.equipment_id,
  CASE
    WHEN {{REQUIRE_OPERATIONAL_GATE}} < 0.5 THEN SUM(CASE WHEN f.confirmed = 1 THEN f.held_seconds ELSE 0.0 END) / 3600.0
    WHEN MAX(c.cov_pct) < {{MINIMUM_ACTIVE_COVERAGE_PCT}} THEN 0.0
    ELSE SUM(CASE WHEN f.confirmed = 1 THEN f.held_seconds ELSE 0.0 END) / 3600.0
  END AS fault_hours,
  SUM(f.held_seconds) / 3600.0 AS covered_hours,
  CASE
    WHEN {{REQUIRE_OPERATIONAL_GATE}} < 0.5 THEN 100.0 * SUM(CASE WHEN f.confirmed = 1 THEN f.held_seconds ELSE 0.0 END) / NULLIF(SUM(f.held_seconds), 0.0)
    WHEN MAX(c.cov_pct) < {{MINIMUM_ACTIVE_COVERAGE_PCT}} THEN 0.0
    ELSE 100.0 * SUM(CASE WHEN f.confirmed = 1 THEN f.held_seconds ELSE 0.0 END) / NULLIF(SUM(f.held_seconds), 0.0)
  END AS fault_pct
FROM final f
LEFT JOIN cov c ON f.equipment_id = c.equipment_id
GROUP BY f.equipment_id;
```
{% endraw %}

### fc14_chw_coil_dt_inactive.sql

`sql/fdd/postgres/rules/fc14_chw_coil_dt_inactive.sql`

{% raw %}
```sql
-- PostgreSQL adaptation. Render numeric template parameters with render_rule.py.
-- Inputs must be scoped to one tenant/site and cadence; see README.md.
-- fc14_chw_coil_dt_inactive.sql — CHW coil ΔT when inactive (GL36 L)
-- Prefer dedicated coil temps; fall back to MAT/SAT proxy when coil sensors absent.
WITH h AS (
  SELECT
    equipment_id,
    timestamp_utc,
    COALESCE(cooling_coil_entering_temp, mat) AS enter_t,
    COALESCE(cooling_coil_leaving_temp, sat) AS leave_t,
    CASE WHEN clg_valve_pct IS NULL THEN 0.0 WHEN clg_valve_pct > 1.0 THEN clg_valve_pct / 100.0 ELSE clg_valve_pct END AS clg,
    CASE WHEN oa_damper_pct IS NULL THEN 0.0 WHEN oa_damper_pct > 1.0 THEN oa_damper_pct / 100.0 ELSE oa_damper_pct END AS oa_d,
    CASE WHEN fan_cmd IS NULL THEN 0.0 WHEN fan_cmd > 1.0 THEN fan_cmd / 100.0 ELSE fan_cmd END AS fan,
        CASE
      WHEN {{REQUIRE_OPERATIONAL_GATE}} < 0.5 THEN 1
      WHEN fan_status IS NOT NULL THEN CASE WHEN fan_status > 0.05 THEN 1 ELSE 0 END
      WHEN fan_cmd IS NOT NULL THEN CASE WHEN (CASE WHEN fan_cmd > 1.0 THEN fan_cmd / 100.0 ELSE fan_cmd END) > {{FAN_ON_MIN}} THEN 1 ELSE 0 END
      ELSE 1
    END AS fan_on
  FROM history
),
base AS (
  SELECT
    equipment_id,
    timestamp_utc,
    CAST(CASE
      WHEN COALESCE(fan_on, 1) = 0 THEN 0
      WHEN COALESCE(mode_stable, 1) = 0 THEN 0
      WHEN enter_t IS NULL OR leave_t IS NULL THEN 0
      WHEN fan < {{FAN_ON_MIN}} THEN 0
      WHEN clg > {{CLG_ON_MIN}} THEN 0
      WHEN ABS(enter_t - leave_t) >= SQRT(2.0 * {{EPS_MAT}} * {{EPS_MAT}}) + {{DELTA_SUPPLY_FAN}} THEN 1
      ELSE 0
    END AS INT) AS raw_fault
  FROM (
  SELECT h.*,
    CASE
      WHEN COALESCE(fan_on, 1) = 0 THEN 0
      WHEN SUM(CASE WHEN COALESCE(fan_on, 1) = 0 THEN 1 ELSE 0 END) OVER (
        PARTITION BY equipment_id ORDER BY timestamp_utc
        ROWS BETWEEN {{MODE_DELAY_ROWS_PRECEDING}} PRECEDING AND CURRENT ROW
      ) = 0 THEN 1
      ELSE 0
    END AS mode_stable
  FROM h
) h
),
elapsed_hold AS (
  -- Forward sample-and-hold. A gap longer than MAX_GAP_HOURS is unknown:
  -- it is not fault time, not covered time, and it breaks confirmation.
  -- The last sample has no forward interval.
  SELECT
    stepped.*,
    CASE
      WHEN stepped.dt_seconds IS NULL
        OR stepped.dt_seconds <= 0.0
        OR stepped.dt_seconds > ({{MAX_GAP_HOURS}} * 3600.0)
      THEN 0.0
      ELSE stepped.dt_seconds
    END AS held_seconds,
    CASE
      WHEN stepped.dt_seconds > ({{MAX_GAP_HOURS}} * 3600.0) THEN 1
      ELSE 0
    END AS gap_after
  FROM (
    SELECT
      src.*,
      EXTRACT(EPOCH FROM (
        LEAD(src.timestamp_utc) OVER (
          PARTITION BY src.equipment_id ORDER BY src.timestamp_utc
        ) - src.timestamp_utc
      )) AS dt_seconds
    FROM base src
  ) stepped
),
lagged AS (
  SELECT
    *,
    CASE
      WHEN raw_fault = LAG(raw_fault) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc)
       AND COALESCE(LAG(gap_after) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc), 0) = 0
      THEN 0 ELSE 1
    END AS is_new_streak
  FROM elapsed_hold
),
grp AS (
  SELECT
    *,
    SUM(is_new_streak)
      OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS UNBOUNDED PRECEDING) AS streak_id
  FROM lagged
),
ranked AS (
  SELECT
    *,
    SUM(held_seconds) OVER (
      PARTITION BY equipment_id, streak_id ORDER BY timestamp_utc
      ROWS UNBOUNDED PRECEDING
    ) AS streak_elapsed
  FROM grp
),
final AS (
  SELECT
    equipment_id,
    held_seconds,
    CASE WHEN raw_fault = 1 AND streak_elapsed >= {{CONFIRM_SECONDS}} THEN 1 ELSE 0 END AS confirmed
  FROM ranked
)
, cov AS (
  SELECT equipment_id,
    100.0 * AVG(CAST(COALESCE(fan_on, 1) AS DOUBLE PRECISION)) AS cov_pct
  FROM h
  GROUP BY equipment_id
)
SELECT
  f.equipment_id,
  CASE
    WHEN {{REQUIRE_OPERATIONAL_GATE}} < 0.5 THEN SUM(CASE WHEN f.confirmed = 1 THEN f.held_seconds ELSE 0.0 END) / 3600.0
    WHEN MAX(c.cov_pct) < {{MINIMUM_ACTIVE_COVERAGE_PCT}} THEN 0.0
    ELSE SUM(CASE WHEN f.confirmed = 1 THEN f.held_seconds ELSE 0.0 END) / 3600.0
  END AS fault_hours,
  SUM(f.held_seconds) / 3600.0 AS covered_hours,
  CASE
    WHEN {{REQUIRE_OPERATIONAL_GATE}} < 0.5 THEN 100.0 * SUM(CASE WHEN f.confirmed = 1 THEN f.held_seconds ELSE 0.0 END) / NULLIF(SUM(f.held_seconds), 0.0)
    WHEN MAX(c.cov_pct) < {{MINIMUM_ACTIVE_COVERAGE_PCT}} THEN 0.0
    ELSE 100.0 * SUM(CASE WHEN f.confirmed = 1 THEN f.held_seconds ELSE 0.0 END) / NULLIF(SUM(f.held_seconds), 0.0)
  END AS fault_pct
FROM final f
LEFT JOIN cov c ON f.equipment_id = c.equipment_id
GROUP BY f.equipment_id;
```
{% endraw %}

### fc15_hw_coil_dt_inactive.sql

`sql/fdd/postgres/rules/fc15_hw_coil_dt_inactive.sql`

{% raw %}
```sql
-- PostgreSQL adaptation. Render numeric template parameters with render_rule.py.
-- Inputs must be scoped to one tenant/site and cadence; see README.md.
-- fc15_hw_coil_dt_inactive.sql — HW coil ΔT when inactive (GL36 M)
-- Prefer dedicated HW coil temps; fall back to MAT/SAT. Inactive gate uses
-- cooling-valve (pandas) when heating-valve is absent.
WITH h AS (
  SELECT
    equipment_id,
    timestamp_utc,
    COALESCE(heating_coil_entering_temp, mat) AS enter_t,
    COALESCE(heating_coil_leaving_temp, sat) AS leave_t,
    CASE WHEN htg_valve_pct IS NULL THEN 0.0 WHEN htg_valve_pct > 1.0 THEN htg_valve_pct / 100.0 ELSE htg_valve_pct END AS htg,
    CASE WHEN clg_valve_pct IS NULL THEN 0.0 WHEN clg_valve_pct > 1.0 THEN clg_valve_pct / 100.0 ELSE clg_valve_pct END AS clg,
    CASE WHEN fan_cmd IS NULL THEN 0.0 WHEN fan_cmd > 1.0 THEN fan_cmd / 100.0 ELSE fan_cmd END AS fan,
        CASE
      WHEN {{REQUIRE_OPERATIONAL_GATE}} < 0.5 THEN 1
      WHEN fan_status IS NOT NULL THEN CASE WHEN fan_status > 0.05 THEN 1 ELSE 0 END
      WHEN fan_cmd IS NOT NULL THEN CASE WHEN (CASE WHEN fan_cmd > 1.0 THEN fan_cmd / 100.0 ELSE fan_cmd END) > {{FAN_ON_MIN}} THEN 1 ELSE 0 END
      ELSE 1
    END AS fan_on
  FROM history
),
base AS (
  SELECT
    equipment_id,
    timestamp_utc,
    CAST(CASE
      WHEN COALESCE(fan_on, 1) = 0 THEN 0
      WHEN COALESCE(mode_stable, 1) = 0 THEN 0
      WHEN enter_t IS NULL OR leave_t IS NULL THEN 0
      WHEN fan < {{FAN_ON_MIN}} THEN 0
      WHEN htg > {{HTG_ON_MIN}} THEN 0
      WHEN clg > {{CLG_ON_MIN}} THEN 0
      WHEN ABS(enter_t - leave_t) >= SQRT(2.0 * {{EPS_MAT}} * {{EPS_MAT}}) + {{DELTA_SUPPLY_FAN}} THEN 1
      ELSE 0
    END AS INT) AS raw_fault
  FROM (
  SELECT h.*,
    CASE
      WHEN COALESCE(fan_on, 1) = 0 THEN 0
      WHEN SUM(CASE WHEN COALESCE(fan_on, 1) = 0 THEN 1 ELSE 0 END) OVER (
        PARTITION BY equipment_id ORDER BY timestamp_utc
        ROWS BETWEEN {{MODE_DELAY_ROWS_PRECEDING}} PRECEDING AND CURRENT ROW
      ) = 0 THEN 1
      ELSE 0
    END AS mode_stable
  FROM h
) h
),
elapsed_hold AS (
  -- Forward sample-and-hold. A gap longer than MAX_GAP_HOURS is unknown:
  -- it is not fault time, not covered time, and it breaks confirmation.
  -- The last sample has no forward interval.
  SELECT
    stepped.*,
    CASE
      WHEN stepped.dt_seconds IS NULL
        OR stepped.dt_seconds <= 0.0
        OR stepped.dt_seconds > ({{MAX_GAP_HOURS}} * 3600.0)
      THEN 0.0
      ELSE stepped.dt_seconds
    END AS held_seconds,
    CASE
      WHEN stepped.dt_seconds > ({{MAX_GAP_HOURS}} * 3600.0) THEN 1
      ELSE 0
    END AS gap_after
  FROM (
    SELECT
      src.*,
      EXTRACT(EPOCH FROM (
        LEAD(src.timestamp_utc) OVER (
          PARTITION BY src.equipment_id ORDER BY src.timestamp_utc
        ) - src.timestamp_utc
      )) AS dt_seconds
    FROM base src
  ) stepped
),
lagged AS (
  SELECT
    *,
    CASE
      WHEN raw_fault = LAG(raw_fault) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc)
       AND COALESCE(LAG(gap_after) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc), 0) = 0
      THEN 0 ELSE 1
    END AS is_new_streak
  FROM elapsed_hold
),
grp AS (
  SELECT
    *,
    SUM(is_new_streak)
      OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS UNBOUNDED PRECEDING) AS streak_id
  FROM lagged
),
ranked AS (
  SELECT
    *,
    SUM(held_seconds) OVER (
      PARTITION BY equipment_id, streak_id ORDER BY timestamp_utc
      ROWS UNBOUNDED PRECEDING
    ) AS streak_elapsed
  FROM grp
),
final AS (
  SELECT
    equipment_id,
    held_seconds,
    CASE WHEN raw_fault = 1 AND streak_elapsed >= {{CONFIRM_SECONDS}} THEN 1 ELSE 0 END AS confirmed
  FROM ranked
)
, cov AS (
  SELECT equipment_id,
    100.0 * AVG(CAST(COALESCE(fan_on, 1) AS DOUBLE PRECISION)) AS cov_pct
  FROM h
  GROUP BY equipment_id
)
SELECT
  f.equipment_id,
  CASE
    WHEN {{REQUIRE_OPERATIONAL_GATE}} < 0.5 THEN SUM(CASE WHEN f.confirmed = 1 THEN f.held_seconds ELSE 0.0 END) / 3600.0
    WHEN MAX(c.cov_pct) < {{MINIMUM_ACTIVE_COVERAGE_PCT}} THEN 0.0
    ELSE SUM(CASE WHEN f.confirmed = 1 THEN f.held_seconds ELSE 0.0 END) / 3600.0
  END AS fault_hours,
  SUM(f.held_seconds) / 3600.0 AS covered_hours,
  CASE
    WHEN {{REQUIRE_OPERATIONAL_GATE}} < 0.5 THEN 100.0 * SUM(CASE WHEN f.confirmed = 1 THEN f.held_seconds ELSE 0.0 END) / NULLIF(SUM(f.held_seconds), 0.0)
    WHEN MAX(c.cov_pct) < {{MINIMUM_ACTIVE_COVERAGE_PCT}} THEN 0.0
    ELSE 100.0 * SUM(CASE WHEN f.confirmed = 1 THEN f.held_seconds ELSE 0.0 END) / NULLIF(SUM(f.held_seconds), 0.0)
  END AS fault_pct
FROM final f
LEFT JOIN cov c ON f.equipment_id = c.equipment_id
GROUP BY f.equipment_id;
```
{% endraw %}

### fc1_duct_static_low.sql

`sql/fdd/postgres/rules/fc1_duct_static_low.sql`

{% raw %}
```sql
-- PostgreSQL adaptation. Render numeric template parameters with render_rule.py.
-- Inputs must be scoped to one tenant/site and cadence; see README.md.
-- fc1_duct_static_low.sql — FC1 duct static below SP at full fan + confirm
WITH h AS (
  SELECT
    equipment_id,
    timestamp_utc,
    duct_static,
    duct_static_sp,
    CASE WHEN fan_cmd IS NULL THEN NULL WHEN fan_cmd > 1.0 THEN fan_cmd / 100.0 ELSE fan_cmd END AS fan_cmd,
        CASE
      WHEN {{REQUIRE_OPERATIONAL_GATE}} < 0.5 THEN 1
      WHEN fan_status IS NOT NULL THEN CASE WHEN fan_status > 0.05 THEN 1 ELSE 0 END
      WHEN fan_cmd IS NOT NULL THEN CASE WHEN (CASE WHEN fan_cmd > 1.0 THEN fan_cmd / 100.0 ELSE fan_cmd END) > {{FAN_ON_MIN}} THEN 1 ELSE 0 END
      ELSE 1
    END AS fan_on,
    -- Match pandas cookbook `_fan()`: prefer fan_status for the "full fan" gate.
    -- Synth-59 AHU_CASE_FC1 has status=1 with cmd=0.6 for most fault hours;
    -- cmd-only gating under-counts (1h vs 40h).
    CASE
      WHEN fan_status IS NOT NULL THEN CASE WHEN fan_status > 0.05 THEN 1.0 ELSE 0.0 END
      ELSE CASE WHEN fan_cmd IS NULL THEN NULL WHEN fan_cmd > 1.0 THEN fan_cmd / 100.0 ELSE fan_cmd END
    END AS fan_for_hi
  FROM history
),
base AS (
  SELECT
    equipment_id,
    timestamp_utc,
    CAST(CASE
      WHEN COALESCE(fan_on, 1) = 0 THEN 0
      WHEN COALESCE(mode_stable, 1) = 0 THEN 0
      WHEN duct_static IS NOT NULL AND duct_static_sp IS NOT NULL
       AND duct_static < duct_static_sp - {{EPS_DSP}}
       AND fan_for_hi >= 1.0 - {{EPS_VFD_SPD}}
      THEN 1 ELSE 0 END AS INT) AS raw_fault
  FROM (
  SELECT h.*,
    CASE
      WHEN COALESCE(fan_on, 1) = 0 THEN 0
      WHEN SUM(CASE WHEN COALESCE(fan_on, 1) = 0 THEN 1 ELSE 0 END) OVER (
        PARTITION BY equipment_id ORDER BY timestamp_utc
        ROWS BETWEEN {{MODE_DELAY_ROWS_PRECEDING}} PRECEDING AND CURRENT ROW
      ) = 0 THEN 1
      ELSE 0
    END AS mode_stable
  FROM h
) h
),
elapsed_hold AS (
  -- Forward sample-and-hold. A gap longer than MAX_GAP_HOURS is unknown:
  -- it is not fault time, not covered time, and it breaks confirmation.
  -- The last sample has no forward interval.
  SELECT
    stepped.*,
    CASE
      WHEN stepped.dt_seconds IS NULL
        OR stepped.dt_seconds <= 0.0
        OR stepped.dt_seconds > ({{MAX_GAP_HOURS}} * 3600.0)
      THEN 0.0
      ELSE stepped.dt_seconds
    END AS held_seconds,
    CASE
      WHEN stepped.dt_seconds > ({{MAX_GAP_HOURS}} * 3600.0) THEN 1
      ELSE 0
    END AS gap_after
  FROM (
    SELECT
      src.*,
      EXTRACT(EPOCH FROM (
        LEAD(src.timestamp_utc) OVER (
          PARTITION BY src.equipment_id ORDER BY src.timestamp_utc
        ) - src.timestamp_utc
      )) AS dt_seconds
    FROM base src
  ) stepped
),
lagged AS (
  SELECT
    *,
    CASE
      WHEN raw_fault = LAG(raw_fault) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc)
       AND COALESCE(LAG(gap_after) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc), 0) = 0
      THEN 0 ELSE 1
    END AS is_new_streak
  FROM elapsed_hold
),
grp AS (
  SELECT
    *,
    SUM(is_new_streak)
      OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS UNBOUNDED PRECEDING) AS streak_id
  FROM lagged
),
ranked AS (
  SELECT
    *,
    SUM(held_seconds) OVER (
      PARTITION BY equipment_id, streak_id ORDER BY timestamp_utc
      ROWS UNBOUNDED PRECEDING
    ) AS streak_elapsed
  FROM grp
),
final AS (
  SELECT
    equipment_id,
    held_seconds,
    CASE WHEN raw_fault = 1 AND streak_elapsed >= {{CONFIRM_SECONDS}} THEN 1 ELSE 0 END AS confirmed
  FROM ranked
)
, cov AS (
  SELECT equipment_id,
    100.0 * AVG(CAST(COALESCE(fan_on, 1) AS DOUBLE PRECISION)) AS cov_pct
  FROM h
  GROUP BY equipment_id
)
SELECT
  f.equipment_id,
  CASE
    WHEN {{REQUIRE_OPERATIONAL_GATE}} < 0.5 THEN SUM(CASE WHEN f.confirmed = 1 THEN f.held_seconds ELSE 0.0 END) / 3600.0
    WHEN MAX(c.cov_pct) < {{MINIMUM_ACTIVE_COVERAGE_PCT}} THEN 0.0
    ELSE SUM(CASE WHEN f.confirmed = 1 THEN f.held_seconds ELSE 0.0 END) / 3600.0
  END AS fault_hours,
  SUM(f.held_seconds) / 3600.0 AS covered_hours,
  CASE
    WHEN {{REQUIRE_OPERATIONAL_GATE}} < 0.5 THEN 100.0 * SUM(CASE WHEN f.confirmed = 1 THEN f.held_seconds ELSE 0.0 END) / NULLIF(SUM(f.held_seconds), 0.0)
    WHEN MAX(c.cov_pct) < {{MINIMUM_ACTIVE_COVERAGE_PCT}} THEN 0.0
    ELSE 100.0 * SUM(CASE WHEN f.confirmed = 1 THEN f.held_seconds ELSE 0.0 END) / NULLIF(SUM(f.held_seconds), 0.0)
  END AS fault_pct
FROM final f
LEFT JOIN cov c ON f.equipment_id = c.equipment_id
GROUP BY f.equipment_id;
```
{% endraw %}

### fc2_mat_low.sql

`sql/fdd/postgres/rules/fc2_mat_low.sql`

{% raw %}
```sql
-- PostgreSQL adaptation. Render numeric template parameters with render_rule.py.
-- Inputs must be scoped to one tenant/site and cadence; see README.md.
-- fc2_mat_low.sql — FC2 mixed air below envelope + confirm (600s default)
WITH h AS (
  SELECT
    equipment_id,
    timestamp_utc,
    mat,
    oa_t,
    rat,
    COALESCE(CASE WHEN fan_cmd IS NULL THEN 0.0 WHEN fan_cmd > 1.0 THEN fan_cmd / 100.0 ELSE fan_cmd END, 0.0) AS fan,
        CASE
      WHEN {{REQUIRE_OPERATIONAL_GATE}} < 0.5 THEN 1
      WHEN fan_status IS NOT NULL THEN CASE WHEN fan_status > 0.05 THEN 1 ELSE 0 END
      WHEN fan_cmd IS NOT NULL THEN CASE WHEN (CASE WHEN fan_cmd > 1.0 THEN fan_cmd / 100.0 ELSE fan_cmd END) > {{FAN_ON_MIN}} THEN 1 ELSE 0 END
      ELSE 1
    END AS fan_on

  FROM history
),
base AS (
  SELECT
    equipment_id,
    timestamp_utc,
    CAST(CASE
      WHEN COALESCE(fan_on, 1) = 0 THEN 0
      WHEN COALESCE(mode_stable, 1) = 0 THEN 0
      WHEN mat IS NOT NULL AND oa_t IS NOT NULL AND rat IS NOT NULL
       AND (mat + {{EPS_MAT}}) < (CASE WHEN rat < oa_t THEN rat - {{EPS_RAT}} ELSE oa_t - {{EPS_OAT}} END)
      THEN 1 ELSE 0 END AS INT) AS raw_fault
  FROM (
  SELECT h.*,
    CASE
      WHEN COALESCE(fan_on, 1) = 0 THEN 0
      WHEN SUM(CASE WHEN COALESCE(fan_on, 1) = 0 THEN 1 ELSE 0 END) OVER (
        PARTITION BY equipment_id ORDER BY timestamp_utc
        ROWS BETWEEN {{MODE_DELAY_ROWS_PRECEDING}} PRECEDING AND CURRENT ROW
      ) = 0 THEN 1
      ELSE 0
    END AS mode_stable
  FROM h
) h
),
elapsed_hold AS (
  -- Forward sample-and-hold. A gap longer than MAX_GAP_HOURS is unknown:
  -- it is not fault time, not covered time, and it breaks confirmation.
  -- The last sample has no forward interval.
  SELECT
    stepped.*,
    CASE
      WHEN stepped.dt_seconds IS NULL
        OR stepped.dt_seconds <= 0.0
        OR stepped.dt_seconds > ({{MAX_GAP_HOURS}} * 3600.0)
      THEN 0.0
      ELSE stepped.dt_seconds
    END AS held_seconds,
    CASE
      WHEN stepped.dt_seconds > ({{MAX_GAP_HOURS}} * 3600.0) THEN 1
      ELSE 0
    END AS gap_after
  FROM (
    SELECT
      src.*,
      EXTRACT(EPOCH FROM (
        LEAD(src.timestamp_utc) OVER (
          PARTITION BY src.equipment_id ORDER BY src.timestamp_utc
        ) - src.timestamp_utc
      )) AS dt_seconds
    FROM base src
  ) stepped
),
lagged AS (
  SELECT
    *,
    CASE
      WHEN raw_fault = LAG(raw_fault) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc)
       AND COALESCE(LAG(gap_after) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc), 0) = 0
      THEN 0 ELSE 1
    END AS is_new_streak
  FROM elapsed_hold
),
grp AS (
  SELECT
    *,
    SUM(is_new_streak)
      OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS UNBOUNDED PRECEDING) AS streak_id
  FROM lagged
),
ranked AS (
  SELECT
    *,
    SUM(held_seconds) OVER (
      PARTITION BY equipment_id, streak_id ORDER BY timestamp_utc
      ROWS UNBOUNDED PRECEDING
    ) AS streak_elapsed
  FROM grp
),
final AS (
  SELECT
    equipment_id,
    held_seconds,
    CASE WHEN raw_fault = 1 AND streak_elapsed >= {{CONFIRM_SECONDS}} THEN 1 ELSE 0 END AS confirmed
  FROM ranked
)
, cov AS (
  SELECT equipment_id,
    100.0 * AVG(CAST(COALESCE(fan_on, 1) AS DOUBLE PRECISION)) AS cov_pct
  FROM h
  GROUP BY equipment_id
)
SELECT
  f.equipment_id,
  CASE
    WHEN {{REQUIRE_OPERATIONAL_GATE}} < 0.5 THEN SUM(CASE WHEN f.confirmed = 1 THEN f.held_seconds ELSE 0.0 END) / 3600.0
    WHEN MAX(c.cov_pct) < {{MINIMUM_ACTIVE_COVERAGE_PCT}} THEN 0.0
    ELSE SUM(CASE WHEN f.confirmed = 1 THEN f.held_seconds ELSE 0.0 END) / 3600.0
  END AS fault_hours,
  SUM(f.held_seconds) / 3600.0 AS covered_hours,
  CASE
    WHEN {{REQUIRE_OPERATIONAL_GATE}} < 0.5 THEN 100.0 * SUM(CASE WHEN f.confirmed = 1 THEN f.held_seconds ELSE 0.0 END) / NULLIF(SUM(f.held_seconds), 0.0)
    WHEN MAX(c.cov_pct) < {{MINIMUM_ACTIVE_COVERAGE_PCT}} THEN 0.0
    ELSE 100.0 * SUM(CASE WHEN f.confirmed = 1 THEN f.held_seconds ELSE 0.0 END) / NULLIF(SUM(f.held_seconds), 0.0)
  END AS fault_pct
FROM final f
LEFT JOIN cov c ON f.equipment_id = c.equipment_id
GROUP BY f.equipment_id;
```
{% endraw %}

### fc3_mat_high.sql

`sql/fdd/postgres/rules/fc3_mat_high.sql`

{% raw %}
```sql
-- PostgreSQL adaptation. Render numeric template parameters with render_rule.py.
-- Inputs must be scoped to one tenant/site and cadence; see README.md.
-- fc3_mat_high.sql — FC3 mixed air above envelope + confirm (600s default)
WITH h AS (
  SELECT
    equipment_id,
    timestamp_utc,
    mat,
    oa_t,
    rat,
    COALESCE(CASE WHEN fan_cmd IS NULL THEN 0.0 WHEN fan_cmd > 1.0 THEN fan_cmd / 100.0 ELSE fan_cmd END, 0.0) AS fan,
        CASE
      WHEN {{REQUIRE_OPERATIONAL_GATE}} < 0.5 THEN 1
      WHEN fan_status IS NOT NULL THEN CASE WHEN fan_status > 0.05 THEN 1 ELSE 0 END
      WHEN fan_cmd IS NOT NULL THEN CASE WHEN (CASE WHEN fan_cmd > 1.0 THEN fan_cmd / 100.0 ELSE fan_cmd END) > {{FAN_ON_MIN}} THEN 1 ELSE 0 END
      ELSE 1
    END AS fan_on

  FROM history
),
base AS (
  SELECT
    equipment_id,
    timestamp_utc,
    CAST(CASE
      WHEN COALESCE(fan_on, 1) = 0 THEN 0
      WHEN COALESCE(mode_stable, 1) = 0 THEN 0
      WHEN mat IS NOT NULL AND oa_t IS NOT NULL AND rat IS NOT NULL
       AND (mat - {{EPS_MAT}}) > (CASE WHEN rat > oa_t THEN rat + {{EPS_RAT}} ELSE oa_t + {{EPS_OAT}} END)
      THEN 1 ELSE 0 END AS INT) AS raw_fault
  FROM (
  SELECT h.*,
    CASE
      WHEN COALESCE(fan_on, 1) = 0 THEN 0
      WHEN SUM(CASE WHEN COALESCE(fan_on, 1) = 0 THEN 1 ELSE 0 END) OVER (
        PARTITION BY equipment_id ORDER BY timestamp_utc
        ROWS BETWEEN {{MODE_DELAY_ROWS_PRECEDING}} PRECEDING AND CURRENT ROW
      ) = 0 THEN 1
      ELSE 0
    END AS mode_stable
  FROM h
) h
),
elapsed_hold AS (
  -- Forward sample-and-hold. A gap longer than MAX_GAP_HOURS is unknown:
  -- it is not fault time, not covered time, and it breaks confirmation.
  -- The last sample has no forward interval.
  SELECT
    stepped.*,
    CASE
      WHEN stepped.dt_seconds IS NULL
        OR stepped.dt_seconds <= 0.0
        OR stepped.dt_seconds > ({{MAX_GAP_HOURS}} * 3600.0)
      THEN 0.0
      ELSE stepped.dt_seconds
    END AS held_seconds,
    CASE
      WHEN stepped.dt_seconds > ({{MAX_GAP_HOURS}} * 3600.0) THEN 1
      ELSE 0
    END AS gap_after
  FROM (
    SELECT
      src.*,
      EXTRACT(EPOCH FROM (
        LEAD(src.timestamp_utc) OVER (
          PARTITION BY src.equipment_id ORDER BY src.timestamp_utc
        ) - src.timestamp_utc
      )) AS dt_seconds
    FROM base src
  ) stepped
),
lagged AS (
  SELECT
    *,
    CASE
      WHEN raw_fault = LAG(raw_fault) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc)
       AND COALESCE(LAG(gap_after) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc), 0) = 0
      THEN 0 ELSE 1
    END AS is_new_streak
  FROM elapsed_hold
),
grp AS (
  SELECT
    *,
    SUM(is_new_streak)
      OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS UNBOUNDED PRECEDING) AS streak_id
  FROM lagged
),
ranked AS (
  SELECT
    *,
    SUM(held_seconds) OVER (
      PARTITION BY equipment_id, streak_id ORDER BY timestamp_utc
      ROWS UNBOUNDED PRECEDING
    ) AS streak_elapsed
  FROM grp
),
final AS (
  SELECT
    equipment_id,
    held_seconds,
    CASE WHEN raw_fault = 1 AND streak_elapsed >= {{CONFIRM_SECONDS}} THEN 1 ELSE 0 END AS confirmed
  FROM ranked
)
, cov AS (
  SELECT equipment_id,
    100.0 * AVG(CAST(COALESCE(fan_on, 1) AS DOUBLE PRECISION)) AS cov_pct
  FROM h
  GROUP BY equipment_id
)
SELECT
  f.equipment_id,
  CASE
    WHEN {{REQUIRE_OPERATIONAL_GATE}} < 0.5 THEN SUM(CASE WHEN f.confirmed = 1 THEN f.held_seconds ELSE 0.0 END) / 3600.0
    WHEN MAX(c.cov_pct) < {{MINIMUM_ACTIVE_COVERAGE_PCT}} THEN 0.0
    ELSE SUM(CASE WHEN f.confirmed = 1 THEN f.held_seconds ELSE 0.0 END) / 3600.0
  END AS fault_hours,
  SUM(f.held_seconds) / 3600.0 AS covered_hours,
  CASE
    WHEN {{REQUIRE_OPERATIONAL_GATE}} < 0.5 THEN 100.0 * SUM(CASE WHEN f.confirmed = 1 THEN f.held_seconds ELSE 0.0 END) / NULLIF(SUM(f.held_seconds), 0.0)
    WHEN MAX(c.cov_pct) < {{MINIMUM_ACTIVE_COVERAGE_PCT}} THEN 0.0
    ELSE 100.0 * SUM(CASE WHEN f.confirmed = 1 THEN f.held_seconds ELSE 0.0 END) / NULLIF(SUM(f.held_seconds), 0.0)
  END AS fault_pct
FROM final f
LEFT JOIN cov c ON f.equipment_id = c.equipment_id
GROUP BY f.equipment_id;
```
{% endraw %}

### fc4_os_hunting.sql

`sql/fdd/postgres/rules/fc4_os_hunting.sql`

{% raw %}
```sql
-- PostgreSQL adaptation. Render numeric template parameters with render_rule.py.
-- Inputs must be scoped to one tenant/site and cadence; see README.md.
-- fc4_os_hunting.sql — PID hunting (operating-state oscillation), GL36 fault 4
-- ΔOS > ΔOSmax during the clock hour: count how many times the AHU *enters* each
-- operating state within the hour and flag the whole hour when any state is
-- entered more than DELTA_OS_MAX times.
-- Operating states: 1 = min OA / heating, 2 = economizer, 3 = mechanical cooling
-- (0 = fan off, not counted).
WITH h AS (
  SELECT
    equipment_id,
    timestamp_utc,
    CASE WHEN oa_damper_pct IS NULL THEN NULL WHEN oa_damper_pct > 1.0 THEN oa_damper_pct / 100.0 ELSE oa_damper_pct END AS oa_d,
    CASE WHEN clg_valve_pct IS NULL THEN NULL WHEN clg_valve_pct > 1.0 THEN clg_valve_pct / 100.0 ELSE clg_valve_pct END AS clg,
    CASE
      WHEN fan_status IS NOT NULL THEN CASE WHEN fan_status > 0.05 THEN 1.0 ELSE 0.0 END
      WHEN fan_cmd IS NULL THEN NULL
      WHEN fan_cmd > 1.0 THEN fan_cmd / 100.0
      ELSE fan_cmd
    END AS fan,
    CASE
      WHEN {{REQUIRE_OPERATIONAL_GATE}} < 0.5 THEN 1
      WHEN fan_status IS NOT NULL THEN CASE WHEN fan_status > 0.05 THEN 1 ELSE 0 END
      WHEN fan_cmd IS NOT NULL THEN CASE WHEN (CASE WHEN fan_cmd > 1.0 THEN fan_cmd / 100.0 ELSE fan_cmd END) > {{FAN_ON_MIN}} THEN 1 ELSE 0 END
      ELSE 1
    END AS fan_on
  FROM history
),
modes AS (
  SELECT
    equipment_id,
    timestamp_utc,
    DATE_TRUNC('hour', timestamp_utc) AS clock_hour,
    CASE
      WHEN fan IS NULL OR fan < {{FAN_ON_MIN}} THEN 0
      WHEN clg IS NOT NULL AND clg > 0.1 THEN 3
      WHEN oa_d IS NOT NULL AND oa_d > 0.5 THEN 2
      ELSE 1
    END AS op_mode
  FROM h
),
entries AS (
  SELECT
    equipment_id,
    timestamp_utc,
    clock_hour,
    op_mode,
    CASE
      WHEN op_mode = 0 THEN 0
      WHEN LAG(op_mode) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc) IS NULL THEN 0
      WHEN op_mode <> LAG(op_mode) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc) THEN 1
      ELSE 0
    END AS is_entry
  FROM modes
),
hourly AS (
  SELECT
    equipment_id,
    timestamp_utc,
    SUM(CASE WHEN is_entry = 1 AND op_mode = 1 THEN 1 ELSE 0 END)
      OVER (PARTITION BY equipment_id, clock_hour) AS entries_min_oa,
    SUM(CASE WHEN is_entry = 1 AND op_mode = 2 THEN 1 ELSE 0 END)
      OVER (PARTITION BY equipment_id, clock_hour) AS entries_econ,
    SUM(CASE WHEN is_entry = 1 AND op_mode = 3 THEN 1 ELSE 0 END)
      OVER (PARTITION BY equipment_id, clock_hour) AS entries_mech
  FROM entries
),
base AS (
  SELECT
    equipment_id,
    timestamp_utc,
    CAST(CASE
      WHEN entries_min_oa > {{DELTA_OS_MAX}} THEN 1
      WHEN entries_econ > {{DELTA_OS_MAX}} THEN 1
      WHEN entries_mech > {{DELTA_OS_MAX}} THEN 1
      ELSE 0
    END AS INT) AS raw_fault
  FROM hourly
),
elapsed_hold AS (
  -- Forward sample-and-hold. A gap longer than MAX_GAP_HOURS is unknown:
  -- it is not fault time, not covered time, and it breaks confirmation.
  -- The last sample has no forward interval.
  SELECT
    stepped.*,
    CASE
      WHEN stepped.dt_seconds IS NULL
        OR stepped.dt_seconds <= 0.0
        OR stepped.dt_seconds > ({{MAX_GAP_HOURS}} * 3600.0)
      THEN 0.0
      ELSE stepped.dt_seconds
    END AS held_seconds,
    CASE
      WHEN stepped.dt_seconds > ({{MAX_GAP_HOURS}} * 3600.0) THEN 1
      ELSE 0
    END AS gap_after
  FROM (
    SELECT
      src.*,
      EXTRACT(EPOCH FROM (
        LEAD(src.timestamp_utc) OVER (
          PARTITION BY src.equipment_id ORDER BY src.timestamp_utc
        ) - src.timestamp_utc
      )) AS dt_seconds
    FROM base src
  ) stepped
),
lagged AS (
  SELECT
    *,
    CASE
      WHEN raw_fault = LAG(raw_fault) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc)
       AND COALESCE(LAG(gap_after) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc), 0) = 0
      THEN 0 ELSE 1
    END AS is_new_streak
  FROM elapsed_hold
),
grp AS (
  SELECT
    *,
    SUM(is_new_streak)
      OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS UNBOUNDED PRECEDING) AS streak_id
  FROM lagged
),
ranked AS (
  SELECT
    *,
    SUM(held_seconds) OVER (
      PARTITION BY equipment_id, streak_id ORDER BY timestamp_utc
      ROWS UNBOUNDED PRECEDING
    ) AS streak_elapsed
  FROM grp
),
final AS (
  SELECT
    equipment_id,
    held_seconds,
    CASE WHEN raw_fault = 1 AND streak_elapsed >= {{CONFIRM_SECONDS}} THEN 1 ELSE 0 END AS confirmed
  FROM ranked
)
, cov AS (
  SELECT equipment_id,
    100.0 * AVG(CAST(COALESCE(fan_on, 1) AS DOUBLE PRECISION)) AS cov_pct
  FROM h
  GROUP BY equipment_id
)
SELECT
  f.equipment_id,
  CASE
    WHEN {{REQUIRE_OPERATIONAL_GATE}} < 0.5 THEN SUM(CASE WHEN f.confirmed = 1 THEN f.held_seconds ELSE 0.0 END) / 3600.0
    WHEN MAX(c.cov_pct) < {{MINIMUM_ACTIVE_COVERAGE_PCT}} THEN 0.0
    ELSE SUM(CASE WHEN f.confirmed = 1 THEN f.held_seconds ELSE 0.0 END) / 3600.0
  END AS fault_hours,
  SUM(f.held_seconds) / 3600.0 AS covered_hours,
  CASE
    WHEN {{REQUIRE_OPERATIONAL_GATE}} < 0.5 THEN 100.0 * SUM(CASE WHEN f.confirmed = 1 THEN f.held_seconds ELSE 0.0 END) / NULLIF(SUM(f.held_seconds), 0.0)
    WHEN MAX(c.cov_pct) < {{MINIMUM_ACTIVE_COVERAGE_PCT}} THEN 0.0
    ELSE 100.0 * SUM(CASE WHEN f.confirmed = 1 THEN f.held_seconds ELSE 0.0 END) / NULLIF(SUM(f.held_seconds), 0.0)
  END AS fault_pct
FROM final f
LEFT JOIN cov c ON f.equipment_id = c.equipment_id
GROUP BY f.equipment_id;
```
{% endraw %}

### fc5_sat_cold_heating.sql

`sql/fdd/postgres/rules/fc5_sat_cold_heating.sql`

{% raw %}
```sql
-- PostgreSQL adaptation. Render numeric template parameters with render_rule.py.
-- Inputs must be scoped to one tenant/site and cadence; see README.md.
-- fc5_sat_cold_heating.sql — SAT cold when heating commanded (GL36 D)
WITH h AS (
  SELECT
    equipment_id,
    timestamp_utc,
    sat, mat,
    CASE WHEN htg_valve_pct IS NULL THEN NULL WHEN htg_valve_pct > 1.0 THEN htg_valve_pct / 100.0 ELSE htg_valve_pct END AS htg,
    CASE WHEN fan_cmd IS NULL THEN NULL WHEN fan_cmd > 1.0 THEN fan_cmd / 100.0 ELSE fan_cmd END AS fan,
        CASE
      WHEN {{REQUIRE_OPERATIONAL_GATE}} < 0.5 THEN 1
      WHEN fan_status IS NOT NULL THEN CASE WHEN fan_status > 0.05 THEN 1 ELSE 0 END
      WHEN fan_cmd IS NOT NULL THEN CASE WHEN (CASE WHEN fan_cmd > 1.0 THEN fan_cmd / 100.0 ELSE fan_cmd END) > {{FAN_ON_MIN}} THEN 1 ELSE 0 END
      ELSE 1
    END AS fan_on

  FROM history
),
base AS (
  SELECT
    equipment_id,
    timestamp_utc,
    CAST(CASE
      WHEN COALESCE(fan_on, 1) = 0 THEN 0
      WHEN COALESCE(mode_stable, 1) = 0 THEN 0
      WHEN sat IS NULL OR mat IS NULL OR htg IS NULL OR fan IS NULL THEN 0
      WHEN fan >= {{FAN_ON_MIN}} AND htg > {{HTG_ON_MIN}}
       AND (sat + {{EPS_MAT}}) <= (mat - {{EPS_MAT}} + {{DELTA_SUPPLY_FAN}}) THEN 1
      ELSE 0
    END AS INT) AS raw_fault
  FROM (
  SELECT h.*,
    CASE
      WHEN COALESCE(fan_on, 1) = 0 THEN 0
      WHEN SUM(CASE WHEN COALESCE(fan_on, 1) = 0 THEN 1 ELSE 0 END) OVER (
        PARTITION BY equipment_id ORDER BY timestamp_utc
        ROWS BETWEEN {{MODE_DELAY_ROWS_PRECEDING}} PRECEDING AND CURRENT ROW
      ) = 0 THEN 1
      ELSE 0
    END AS mode_stable
  FROM h
) h
),
elapsed_hold AS (
  -- Forward sample-and-hold. A gap longer than MAX_GAP_HOURS is unknown:
  -- it is not fault time, not covered time, and it breaks confirmation.
  -- The last sample has no forward interval.
  SELECT
    stepped.*,
    CASE
      WHEN stepped.dt_seconds IS NULL
        OR stepped.dt_seconds <= 0.0
        OR stepped.dt_seconds > ({{MAX_GAP_HOURS}} * 3600.0)
      THEN 0.0
      ELSE stepped.dt_seconds
    END AS held_seconds,
    CASE
      WHEN stepped.dt_seconds > ({{MAX_GAP_HOURS}} * 3600.0) THEN 1
      ELSE 0
    END AS gap_after
  FROM (
    SELECT
      src.*,
      EXTRACT(EPOCH FROM (
        LEAD(src.timestamp_utc) OVER (
          PARTITION BY src.equipment_id ORDER BY src.timestamp_utc
        ) - src.timestamp_utc
      )) AS dt_seconds
    FROM base src
  ) stepped
),
lagged AS (
  SELECT
    *,
    CASE
      WHEN raw_fault = LAG(raw_fault) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc)
       AND COALESCE(LAG(gap_after) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc), 0) = 0
      THEN 0 ELSE 1
    END AS is_new_streak
  FROM elapsed_hold
),
grp AS (
  SELECT
    *,
    SUM(is_new_streak)
      OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS UNBOUNDED PRECEDING) AS streak_id
  FROM lagged
),
ranked AS (
  SELECT
    *,
    SUM(held_seconds) OVER (
      PARTITION BY equipment_id, streak_id ORDER BY timestamp_utc
      ROWS UNBOUNDED PRECEDING
    ) AS streak_elapsed
  FROM grp
),
final AS (
  SELECT
    equipment_id,
    held_seconds,
    CASE WHEN raw_fault = 1 AND streak_elapsed >= {{CONFIRM_SECONDS}} THEN 1 ELSE 0 END AS confirmed
  FROM ranked
)
, cov AS (
  SELECT equipment_id,
    100.0 * AVG(CAST(COALESCE(fan_on, 1) AS DOUBLE PRECISION)) AS cov_pct
  FROM h
  GROUP BY equipment_id
)
SELECT
  f.equipment_id,
  CASE
    WHEN {{REQUIRE_OPERATIONAL_GATE}} < 0.5 THEN SUM(CASE WHEN f.confirmed = 1 THEN f.held_seconds ELSE 0.0 END) / 3600.0
    WHEN MAX(c.cov_pct) < {{MINIMUM_ACTIVE_COVERAGE_PCT}} THEN 0.0
    ELSE SUM(CASE WHEN f.confirmed = 1 THEN f.held_seconds ELSE 0.0 END) / 3600.0
  END AS fault_hours,
  SUM(f.held_seconds) / 3600.0 AS covered_hours,
  CASE
    WHEN {{REQUIRE_OPERATIONAL_GATE}} < 0.5 THEN 100.0 * SUM(CASE WHEN f.confirmed = 1 THEN f.held_seconds ELSE 0.0 END) / NULLIF(SUM(f.held_seconds), 0.0)
    WHEN MAX(c.cov_pct) < {{MINIMUM_ACTIVE_COVERAGE_PCT}} THEN 0.0
    ELSE 100.0 * SUM(CASE WHEN f.confirmed = 1 THEN f.held_seconds ELSE 0.0 END) / NULLIF(SUM(f.held_seconds), 0.0)
  END AS fault_pct
FROM final f
LEFT JOIN cov c ON f.equipment_id = c.equipment_id
GROUP BY f.equipment_id;
```
{% endraw %}

### fc6_oa_frac_mismatch.sql

`sql/fdd/postgres/rules/fc6_oa_frac_mismatch.sql`

{% raw %}
```sql
-- PostgreSQL adaptation. Render numeric template parameters with render_rule.py.
-- Inputs must be scoped to one tenant/site and cadence; see README.md.
-- fc6_oa_frac_mismatch.sql — Estimated OA fraction mismatch (GL36 fault 6)
-- |RATavg − OATavg| >= ΔTmin AND |estimated OA% − design min OA%| > εF, where
-- design minimum outdoor airflow (L/s) = MIN_L_S_DESIGN / total VAV airflow (L/s).
WITH h AS (
  SELECT
    equipment_id,
    timestamp_utc,
    mat, rat, oa_t, vav_total_flow,
    CASE WHEN fan_cmd IS NULL THEN NULL WHEN fan_cmd > 1.0 THEN fan_cmd / 100.0 ELSE fan_cmd END AS fan,
        CASE
      WHEN {{REQUIRE_OPERATIONAL_GATE}} < 0.5 THEN 1
      WHEN fan_status IS NOT NULL THEN CASE WHEN fan_status > 0.05 THEN 1 ELSE 0 END
      WHEN fan_cmd IS NOT NULL THEN CASE WHEN (CASE WHEN fan_cmd > 1.0 THEN fan_cmd / 100.0 ELSE fan_cmd END) > {{FAN_ON_MIN}} THEN 1 ELSE 0 END
      ELSE 1
    END AS fan_on

  FROM history
),
base AS (
  SELECT
    equipment_id,
    timestamp_utc,
    CAST(CASE
      WHEN COALESCE(fan_on, 1) = 0 THEN 0
      WHEN COALESCE(mode_stable, 1) = 0 THEN 0
      WHEN mat IS NULL OR rat IS NULL OR oa_t IS NULL OR fan IS NULL THEN 0
      WHEN vav_total_flow IS NULL OR vav_total_flow <= 0.0 THEN 0
      WHEN fan < {{FAN_ON_MIN}} THEN 0
      WHEN ABS(rat - oa_t) < {{OAT_RAT_DELTA_MIN}} THEN 0
      WHEN ABS((mat - rat) / NULLIF(oa_t - rat, 0)
               - {{MIN_L_S_DESIGN}} / NULLIF(vav_total_flow, 0)) > {{EPS_AIRFLOW}} THEN 1
      ELSE 0
    END AS INT) AS raw_fault
  FROM (
  SELECT h.*,
    CASE
      WHEN COALESCE(fan_on, 1) = 0 THEN 0
      WHEN SUM(CASE WHEN COALESCE(fan_on, 1) = 0 THEN 1 ELSE 0 END) OVER (
        PARTITION BY equipment_id ORDER BY timestamp_utc
        ROWS BETWEEN {{MODE_DELAY_ROWS_PRECEDING}} PRECEDING AND CURRENT ROW
      ) = 0 THEN 1
      ELSE 0
    END AS mode_stable
  FROM h
) h
),
elapsed_hold AS (
  -- Forward sample-and-hold. A gap longer than MAX_GAP_HOURS is unknown:
  -- it is not fault time, not covered time, and it breaks confirmation.
  -- The last sample has no forward interval.
  SELECT
    stepped.*,
    CASE
      WHEN stepped.dt_seconds IS NULL
        OR stepped.dt_seconds <= 0.0
        OR stepped.dt_seconds > ({{MAX_GAP_HOURS}} * 3600.0)
      THEN 0.0
      ELSE stepped.dt_seconds
    END AS held_seconds,
    CASE
      WHEN stepped.dt_seconds > ({{MAX_GAP_HOURS}} * 3600.0) THEN 1
      ELSE 0
    END AS gap_after
  FROM (
    SELECT
      src.*,
      EXTRACT(EPOCH FROM (
        LEAD(src.timestamp_utc) OVER (
          PARTITION BY src.equipment_id ORDER BY src.timestamp_utc
        ) - src.timestamp_utc
      )) AS dt_seconds
    FROM base src
  ) stepped
),
lagged AS (
  SELECT
    *,
    CASE
      WHEN raw_fault = LAG(raw_fault) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc)
       AND COALESCE(LAG(gap_after) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc), 0) = 0
      THEN 0 ELSE 1
    END AS is_new_streak
  FROM elapsed_hold
),
grp AS (
  SELECT
    *,
    SUM(is_new_streak)
      OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS UNBOUNDED PRECEDING) AS streak_id
  FROM lagged
),
ranked AS (
  SELECT
    *,
    SUM(held_seconds) OVER (
      PARTITION BY equipment_id, streak_id ORDER BY timestamp_utc
      ROWS UNBOUNDED PRECEDING
    ) AS streak_elapsed
  FROM grp
),
final AS (
  SELECT
    equipment_id,
    held_seconds,
    CASE WHEN raw_fault = 1 AND streak_elapsed >= {{CONFIRM_SECONDS}} THEN 1 ELSE 0 END AS confirmed
  FROM ranked
)
, cov AS (
  SELECT equipment_id,
    100.0 * AVG(CAST(COALESCE(fan_on, 1) AS DOUBLE PRECISION)) AS cov_pct
  FROM h
  GROUP BY equipment_id
)
SELECT
  f.equipment_id,
  CASE
    WHEN {{REQUIRE_OPERATIONAL_GATE}} < 0.5 THEN SUM(CASE WHEN f.confirmed = 1 THEN f.held_seconds ELSE 0.0 END) / 3600.0
    WHEN MAX(c.cov_pct) < {{MINIMUM_ACTIVE_COVERAGE_PCT}} THEN 0.0
    ELSE SUM(CASE WHEN f.confirmed = 1 THEN f.held_seconds ELSE 0.0 END) / 3600.0
  END AS fault_hours,
  SUM(f.held_seconds) / 3600.0 AS covered_hours,
  CASE
    WHEN {{REQUIRE_OPERATIONAL_GATE}} < 0.5 THEN 100.0 * SUM(CASE WHEN f.confirmed = 1 THEN f.held_seconds ELSE 0.0 END) / NULLIF(SUM(f.held_seconds), 0.0)
    WHEN MAX(c.cov_pct) < {{MINIMUM_ACTIVE_COVERAGE_PCT}} THEN 0.0
    ELSE 100.0 * SUM(CASE WHEN f.confirmed = 1 THEN f.held_seconds ELSE 0.0 END) / NULLIF(SUM(f.held_seconds), 0.0)
  END AS fault_pct
FROM final f
LEFT JOIN cov c ON f.equipment_id = c.equipment_id
GROUP BY f.equipment_id;
```
{% endraw %}

### fc7_sat_low_heating.sql

`sql/fdd/postgres/rules/fc7_sat_low_heating.sql`

{% raw %}
```sql
-- PostgreSQL adaptation. Render numeric template parameters with render_rule.py.
-- Inputs must be scoped to one tenant/site and cadence; see README.md.
-- fc7_sat_low_heating.sql — FC7 SAT low while heating at full + confirm
WITH h AS (
  SELECT
    equipment_id,
    timestamp_utc,
    sat,
    sat_sp,
    COALESCE(
      CASE
        WHEN fan_status IS NOT NULL THEN CASE WHEN fan_status > 0.05 THEN 1.0 ELSE 0.0 END
        WHEN fan_cmd IS NULL THEN 0.0
        WHEN fan_cmd > 1.0 THEN fan_cmd / 100.0
        ELSE fan_cmd
      END,
      0.0
    ) AS fan,
    CASE
      WHEN {{REQUIRE_OPERATIONAL_GATE}} < 0.5 THEN 1
      WHEN fan_status IS NOT NULL THEN CASE WHEN fan_status > 0.05 THEN 1 ELSE 0 END
      WHEN fan_cmd IS NOT NULL THEN CASE WHEN (CASE WHEN fan_cmd > 1.0 THEN fan_cmd / 100.0 ELSE fan_cmd END) > {{FAN_ON_MIN}} THEN 1 ELSE 0 END
      ELSE 1
    END AS fan_on,
    COALESCE(CASE WHEN htg_valve_pct IS NULL THEN NULL WHEN htg_valve_pct > 1.0 THEN htg_valve_pct / 100.0 ELSE htg_valve_pct END, 0.0) AS htg_valve_pct
  FROM history
),
base AS (
  SELECT
    equipment_id,
    timestamp_utc,
    CAST(CASE
      WHEN sat IS NOT NULL AND sat_sp IS NOT NULL AND fan > {{FAN_ON_MIN}}
       AND sat < sat_sp - {{EPS_SAT}} AND htg_valve_pct >= {{HTG_FULL_MIN}}
      THEN 1 ELSE 0 END AS INT) AS raw_fault
  FROM h
),
elapsed_hold AS (
  -- Forward sample-and-hold. A gap longer than MAX_GAP_HOURS is unknown:
  -- it is not fault time, not covered time, and it breaks confirmation.
  -- The last sample has no forward interval.
  SELECT
    stepped.*,
    CASE
      WHEN stepped.dt_seconds IS NULL
        OR stepped.dt_seconds <= 0.0
        OR stepped.dt_seconds > ({{MAX_GAP_HOURS}} * 3600.0)
      THEN 0.0
      ELSE stepped.dt_seconds
    END AS held_seconds,
    CASE
      WHEN stepped.dt_seconds > ({{MAX_GAP_HOURS}} * 3600.0) THEN 1
      ELSE 0
    END AS gap_after
  FROM (
    SELECT
      src.*,
      EXTRACT(EPOCH FROM (
        LEAD(src.timestamp_utc) OVER (
          PARTITION BY src.equipment_id ORDER BY src.timestamp_utc
        ) - src.timestamp_utc
      )) AS dt_seconds
    FROM base src
  ) stepped
),
lagged AS (
  SELECT
    *,
    CASE
      WHEN raw_fault = LAG(raw_fault) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc)
       AND COALESCE(LAG(gap_after) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc), 0) = 0
      THEN 0 ELSE 1
    END AS is_new_streak
  FROM elapsed_hold
),
grp AS (
  SELECT
    *,
    SUM(is_new_streak)
      OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS UNBOUNDED PRECEDING) AS streak_id
  FROM lagged
),
ranked AS (
  SELECT
    *,
    SUM(held_seconds) OVER (
      PARTITION BY equipment_id, streak_id ORDER BY timestamp_utc
      ROWS UNBOUNDED PRECEDING
    ) AS streak_elapsed
  FROM grp
),
final AS (
  SELECT
    equipment_id,
    held_seconds,
    CASE WHEN raw_fault = 1 AND streak_elapsed >= {{CONFIRM_SECONDS}} THEN 1 ELSE 0 END AS confirmed
  FROM ranked
)
, cov AS (
  SELECT equipment_id,
    100.0 * AVG(CAST(COALESCE(fan_on, 1) AS DOUBLE PRECISION)) AS cov_pct
  FROM h
  GROUP BY equipment_id
)
SELECT
  f.equipment_id,
  CASE
    WHEN {{REQUIRE_OPERATIONAL_GATE}} < 0.5 THEN SUM(CASE WHEN f.confirmed = 1 THEN f.held_seconds ELSE 0.0 END) / 3600.0
    WHEN MAX(c.cov_pct) < {{MINIMUM_ACTIVE_COVERAGE_PCT}} THEN 0.0
    ELSE SUM(CASE WHEN f.confirmed = 1 THEN f.held_seconds ELSE 0.0 END) / 3600.0
  END AS fault_hours,
  SUM(f.held_seconds) / 3600.0 AS covered_hours,
  CASE
    WHEN {{REQUIRE_OPERATIONAL_GATE}} < 0.5 THEN 100.0 * SUM(CASE WHEN f.confirmed = 1 THEN f.held_seconds ELSE 0.0 END) / NULLIF(SUM(f.held_seconds), 0.0)
    WHEN MAX(c.cov_pct) < {{MINIMUM_ACTIVE_COVERAGE_PCT}} THEN 0.0
    ELSE 100.0 * SUM(CASE WHEN f.confirmed = 1 THEN f.held_seconds ELSE 0.0 END) / NULLIF(SUM(f.held_seconds), 0.0)
  END AS fault_pct
FROM final f
LEFT JOIN cov c ON f.equipment_id = c.equipment_id
GROUP BY f.equipment_id;
```
{% endraw %}

### fc8_sat_mat_econ.sql

`sql/fdd/postgres/rules/fc8_sat_mat_econ.sql`

{% raw %}
```sql
-- PostgreSQL adaptation. Render numeric template parameters with render_rule.py.
-- Inputs must be scoped to one tenant/site and cadence; see README.md.
-- fc8_sat_mat_econ.sql — FC8 SAT vs MAT while economizing + confirm
WITH h AS (
  SELECT
    equipment_id,
    timestamp_utc,
    sat,
    mat,
    COALESCE(CASE WHEN oa_damper_pct IS NULL THEN NULL WHEN oa_damper_pct > 1.0 THEN oa_damper_pct / 100.0 ELSE oa_damper_pct END, 0.0) AS oa_damper_pct,
    COALESCE(CASE WHEN clg_valve_pct IS NULL THEN NULL WHEN clg_valve_pct > 1.0 THEN clg_valve_pct / 100.0 ELSE clg_valve_pct END, 0.0) AS clg_valve_pct,
    fan_cmd,
    fan_status,
        CASE
      WHEN {{REQUIRE_OPERATIONAL_GATE}} < 0.5 THEN 1
      WHEN fan_status IS NOT NULL THEN CASE WHEN fan_status > 0.05 THEN 1 ELSE 0 END
      WHEN fan_cmd IS NOT NULL THEN CASE WHEN (CASE WHEN fan_cmd > 1.0 THEN fan_cmd / 100.0 ELSE fan_cmd END) > {{FAN_ON_MIN}} THEN 1 ELSE 0 END
      ELSE 1
    END AS fan_on

  FROM history
),
base AS (
  SELECT
    equipment_id,
    timestamp_utc,
    CAST(CASE
      WHEN COALESCE(fan_on, 1) = 0 THEN 0
      WHEN COALESCE(mode_stable, 1) = 0 THEN 0
      WHEN sat IS NOT NULL AND mat IS NOT NULL
       AND oa_damper_pct > {{ECON_MIN_POS}} AND clg_valve_pct < {{CLG_INACTIVE_MAX}}
       AND ABS(sat - {{DELTA_SUPPLY_FAN}} - mat) > SQRT({{EPS_SAT}} * {{EPS_SAT}} + {{EPS_MAT}} * {{EPS_MAT}})
      THEN 1 ELSE 0 END AS INT) AS raw_fault
  FROM (
  SELECT h.*,
    CASE
      WHEN COALESCE(fan_on, 1) = 0 THEN 0
      WHEN SUM(CASE WHEN COALESCE(fan_on, 1) = 0 THEN 1 ELSE 0 END) OVER (
        PARTITION BY equipment_id ORDER BY timestamp_utc
        ROWS BETWEEN {{MODE_DELAY_ROWS_PRECEDING}} PRECEDING AND CURRENT ROW
      ) = 0 THEN 1
      ELSE 0
    END AS mode_stable
  FROM h
) h
),
elapsed_hold AS (
  -- Forward sample-and-hold. A gap longer than MAX_GAP_HOURS is unknown:
  -- it is not fault time, not covered time, and it breaks confirmation.
  -- The last sample has no forward interval.
  SELECT
    stepped.*,
    CASE
      WHEN stepped.dt_seconds IS NULL
        OR stepped.dt_seconds <= 0.0
        OR stepped.dt_seconds > ({{MAX_GAP_HOURS}} * 3600.0)
      THEN 0.0
      ELSE stepped.dt_seconds
    END AS held_seconds,
    CASE
      WHEN stepped.dt_seconds > ({{MAX_GAP_HOURS}} * 3600.0) THEN 1
      ELSE 0
    END AS gap_after
  FROM (
    SELECT
      src.*,
      EXTRACT(EPOCH FROM (
        LEAD(src.timestamp_utc) OVER (
          PARTITION BY src.equipment_id ORDER BY src.timestamp_utc
        ) - src.timestamp_utc
      )) AS dt_seconds
    FROM base src
  ) stepped
),
lagged AS (
  SELECT
    *,
    CASE
      WHEN raw_fault = LAG(raw_fault) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc)
       AND COALESCE(LAG(gap_after) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc), 0) = 0
      THEN 0 ELSE 1
    END AS is_new_streak
  FROM elapsed_hold
),
grp AS (
  SELECT
    *,
    SUM(is_new_streak)
      OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS UNBOUNDED PRECEDING) AS streak_id
  FROM lagged
),
ranked AS (
  SELECT
    *,
    SUM(held_seconds) OVER (
      PARTITION BY equipment_id, streak_id ORDER BY timestamp_utc
      ROWS UNBOUNDED PRECEDING
    ) AS streak_elapsed
  FROM grp
),
final AS (
  SELECT
    equipment_id,
    held_seconds,
    CASE WHEN raw_fault = 1 AND streak_elapsed >= {{CONFIRM_SECONDS}} THEN 1 ELSE 0 END AS confirmed
  FROM ranked
)
, cov AS (
  SELECT equipment_id,
    100.0 * AVG(CAST(COALESCE(fan_on, 1) AS DOUBLE PRECISION)) AS cov_pct
  FROM h
  GROUP BY equipment_id
)
SELECT
  f.equipment_id,
  CASE
    WHEN {{REQUIRE_OPERATIONAL_GATE}} < 0.5 THEN SUM(CASE WHEN f.confirmed = 1 THEN f.held_seconds ELSE 0.0 END) / 3600.0
    WHEN MAX(c.cov_pct) < {{MINIMUM_ACTIVE_COVERAGE_PCT}} THEN 0.0
    ELSE SUM(CASE WHEN f.confirmed = 1 THEN f.held_seconds ELSE 0.0 END) / 3600.0
  END AS fault_hours,
  SUM(f.held_seconds) / 3600.0 AS covered_hours,
  CASE
    WHEN {{REQUIRE_OPERATIONAL_GATE}} < 0.5 THEN 100.0 * SUM(CASE WHEN f.confirmed = 1 THEN f.held_seconds ELSE 0.0 END) / NULLIF(SUM(f.held_seconds), 0.0)
    WHEN MAX(c.cov_pct) < {{MINIMUM_ACTIVE_COVERAGE_PCT}} THEN 0.0
    ELSE 100.0 * SUM(CASE WHEN f.confirmed = 1 THEN f.held_seconds ELSE 0.0 END) / NULLIF(SUM(f.held_seconds), 0.0)
  END AS fault_pct
FROM final f
LEFT JOIN cov c ON f.equipment_id = c.equipment_id
GROUP BY f.equipment_id;
```
{% endraw %}

### fc9_oa_sat_sp_econ.sql

`sql/fdd/postgres/rules/fc9_oa_sat_sp_econ.sql`

{% raw %}
```sql
-- PostgreSQL adaptation. Render numeric template parameters with render_rule.py.
-- Inputs must be scoped to one tenant/site and cadence; see README.md.
-- fc9_oa_sat_sp_econ.sql — FC9 OAT high vs SAT SP while economizing + confirm
WITH h AS (
  SELECT
    equipment_id,
    timestamp_utc,
    oa_t,
    sat_sp,
    COALESCE(CASE WHEN oa_damper_pct IS NULL THEN NULL WHEN oa_damper_pct > 1.0 THEN oa_damper_pct / 100.0 ELSE oa_damper_pct END, 0.0) AS oa_damper_pct,
    COALESCE(CASE WHEN clg_valve_pct IS NULL THEN NULL WHEN clg_valve_pct > 1.0 THEN clg_valve_pct / 100.0 ELSE clg_valve_pct END, 0.0) AS clg_valve_pct,
    fan_cmd,
    fan_status,
        CASE
      WHEN {{REQUIRE_OPERATIONAL_GATE}} < 0.5 THEN 1
      WHEN fan_status IS NOT NULL THEN CASE WHEN fan_status > 0.05 THEN 1 ELSE 0 END
      WHEN fan_cmd IS NOT NULL THEN CASE WHEN (CASE WHEN fan_cmd > 1.0 THEN fan_cmd / 100.0 ELSE fan_cmd END) > {{FAN_ON_MIN}} THEN 1 ELSE 0 END
      ELSE 1
    END AS fan_on

  FROM history
),
base AS (
  SELECT
    equipment_id,
    timestamp_utc,
    CAST(CASE
      WHEN COALESCE(fan_on, 1) = 0 THEN 0
      WHEN COALESCE(mode_stable, 1) = 0 THEN 0
      WHEN oa_t IS NOT NULL AND sat_sp IS NOT NULL
       AND oa_damper_pct > {{ECON_MIN_POS}} AND clg_valve_pct < {{CLG_INACTIVE_MAX}}
       AND (oa_t - {{EPS_MAT}}) > (sat_sp - {{DELTA_SUPPLY_FAN}} + {{EPS_MAT}})
      THEN 1 ELSE 0 END AS INT) AS raw_fault
  FROM (
  SELECT h.*,
    CASE
      WHEN COALESCE(fan_on, 1) = 0 THEN 0
      WHEN SUM(CASE WHEN COALESCE(fan_on, 1) = 0 THEN 1 ELSE 0 END) OVER (
        PARTITION BY equipment_id ORDER BY timestamp_utc
        ROWS BETWEEN {{MODE_DELAY_ROWS_PRECEDING}} PRECEDING AND CURRENT ROW
      ) = 0 THEN 1
      ELSE 0
    END AS mode_stable
  FROM h
) h
),
elapsed_hold AS (
  -- Forward sample-and-hold. A gap longer than MAX_GAP_HOURS is unknown:
  -- it is not fault time, not covered time, and it breaks confirmation.
  -- The last sample has no forward interval.
  SELECT
    stepped.*,
    CASE
      WHEN stepped.dt_seconds IS NULL
        OR stepped.dt_seconds <= 0.0
        OR stepped.dt_seconds > ({{MAX_GAP_HOURS}} * 3600.0)
      THEN 0.0
      ELSE stepped.dt_seconds
    END AS held_seconds,
    CASE
      WHEN stepped.dt_seconds > ({{MAX_GAP_HOURS}} * 3600.0) THEN 1
      ELSE 0
    END AS gap_after
  FROM (
    SELECT
      src.*,
      EXTRACT(EPOCH FROM (
        LEAD(src.timestamp_utc) OVER (
          PARTITION BY src.equipment_id ORDER BY src.timestamp_utc
        ) - src.timestamp_utc
      )) AS dt_seconds
    FROM base src
  ) stepped
),
lagged AS (
  SELECT
    *,
    CASE
      WHEN raw_fault = LAG(raw_fault) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc)
       AND COALESCE(LAG(gap_after) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc), 0) = 0
      THEN 0 ELSE 1
    END AS is_new_streak
  FROM elapsed_hold
),
grp AS (
  SELECT
    *,
    SUM(is_new_streak)
      OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS UNBOUNDED PRECEDING) AS streak_id
  FROM lagged
),
ranked AS (
  SELECT
    *,
    SUM(held_seconds) OVER (
      PARTITION BY equipment_id, streak_id ORDER BY timestamp_utc
      ROWS UNBOUNDED PRECEDING
    ) AS streak_elapsed
  FROM grp
),
final AS (
  SELECT
    equipment_id,
    held_seconds,
    CASE WHEN raw_fault = 1 AND streak_elapsed >= {{CONFIRM_SECONDS}} THEN 1 ELSE 0 END AS confirmed
  FROM ranked
)
, cov AS (
  SELECT equipment_id,
    100.0 * AVG(CAST(COALESCE(fan_on, 1) AS DOUBLE PRECISION)) AS cov_pct
  FROM h
  GROUP BY equipment_id
)
SELECT
  f.equipment_id,
  CASE
    WHEN {{REQUIRE_OPERATIONAL_GATE}} < 0.5 THEN SUM(CASE WHEN f.confirmed = 1 THEN f.held_seconds ELSE 0.0 END) / 3600.0
    WHEN MAX(c.cov_pct) < {{MINIMUM_ACTIVE_COVERAGE_PCT}} THEN 0.0
    ELSE SUM(CASE WHEN f.confirmed = 1 THEN f.held_seconds ELSE 0.0 END) / 3600.0
  END AS fault_hours,
  SUM(f.held_seconds) / 3600.0 AS covered_hours,
  CASE
    WHEN {{REQUIRE_OPERATIONAL_GATE}} < 0.5 THEN 100.0 * SUM(CASE WHEN f.confirmed = 1 THEN f.held_seconds ELSE 0.0 END) / NULLIF(SUM(f.held_seconds), 0.0)
    WHEN MAX(c.cov_pct) < {{MINIMUM_ACTIVE_COVERAGE_PCT}} THEN 0.0
    ELSE 100.0 * SUM(CASE WHEN f.confirmed = 1 THEN f.held_seconds ELSE 0.0 END) / NULLIF(SUM(f.held_seconds), 0.0)
  END AS fault_pct
FROM final f
LEFT JOIN cov c ON f.equipment_id = c.equipment_id
GROUP BY f.equipment_id;
```
{% endraw %}

### fcu_clg_coil.sql

`sql/fdd/postgres/rules/fcu_clg_coil.sql`

{% raw %}
```sql
-- PostgreSQL adaptation. Render numeric template parameters with render_rule.py.
-- Inputs must be scoped to one tenant/site and cadence; see README.md.
-- fcu_clg_coil.sql — first-class FCU screening rule
WITH normalized AS (
  SELECT equipment_id, timestamp_utc, sat, zone_t, zone_co2,
    CASE WHEN htg_valve_pct IS NULL THEN NULL WHEN htg_valve_pct > 1.0 THEN htg_valve_pct / 100.0 ELSE htg_valve_pct END AS htg,
    CASE WHEN clg_valve_pct IS NULL THEN NULL WHEN clg_valve_pct > 1.0 THEN clg_valve_pct / 100.0 ELSE clg_valve_pct END AS clg,
    CASE WHEN damper_cmd IS NULL THEN NULL WHEN damper_cmd > 1.0 THEN damper_cmd / 100.0 ELSE damper_cmd END AS dcmd,
    CASE WHEN damper_pct IS NULL THEN NULL WHEN damper_pct > 1.0 THEN damper_pct / 100.0 ELSE damper_pct END AS dpos,
    CASE
      WHEN fan_status IS NOT NULL THEN CASE WHEN fan_status > 0.05 THEN 1 ELSE 0 END
      WHEN fan_cmd IS NOT NULL THEN CASE WHEN (CASE WHEN fan_cmd > 1.0 THEN fan_cmd / 100.0 ELSE fan_cmd END) > 0.10 THEN 1 ELSE 0 END
      ELSE 0
    END AS fan_on
  FROM history
), base AS (
  SELECT equipment_id, timestamp_utc,
    CAST(CASE WHEN sat IS NOT NULL AND zone_t IS NOT NULL AND fan_on = 1 AND clg >= {{VALVE_OPEN}} AND htg <= 0.05 AND sat - zone_t >= 0.0 THEN 1 ELSE 0 END AS INT) AS raw_fault
  FROM normalized
), elapsed_hold AS (
  -- Forward sample-and-hold. A gap longer than MAX_GAP_HOURS is unknown:
  -- it is not fault time, not covered time, and it breaks confirmation.
  -- The last sample has no forward interval.
  SELECT
    stepped.*,
    CASE
      WHEN stepped.dt_seconds IS NULL
        OR stepped.dt_seconds <= 0.0
        OR stepped.dt_seconds > ({{MAX_GAP_HOURS}} * 3600.0)
      THEN 0.0
      ELSE stepped.dt_seconds
    END AS held_seconds,
    CASE
      WHEN stepped.dt_seconds > ({{MAX_GAP_HOURS}} * 3600.0) THEN 1
      ELSE 0
    END AS gap_after
  FROM (
    SELECT
      src.*,
      EXTRACT(EPOCH FROM (
        LEAD(src.timestamp_utc) OVER (
          PARTITION BY src.equipment_id ORDER BY src.timestamp_utc
        ) - src.timestamp_utc
      )) AS dt_seconds
    FROM base src
  ) stepped
),
lagged AS (
  SELECT
    *,
    CASE
      WHEN raw_fault = LAG(raw_fault) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc)
       AND COALESCE(LAG(gap_after) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc), 0) = 0
      THEN 0 ELSE 1
    END AS is_new_streak
  FROM elapsed_hold
), grouped AS (
  SELECT *, SUM(is_new_streak) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS UNBOUNDED PRECEDING) AS streak_id
  FROM lagged
), ranked AS (
  SELECT *, SUM(held_seconds) OVER (
      PARTITION BY equipment_id, streak_id ORDER BY timestamp_utc
      ROWS UNBOUNDED PRECEDING
    ) AS streak_elapsed
  FROM grouped
)
SELECT equipment_id,
  SUM(CASE WHEN raw_fault = 1 AND streak_elapsed >= {{CONFIRM_SECONDS}} THEN held_seconds ELSE 0.0 END) / 3600.0 AS fault_hours,
  SUM(held_seconds) / 3600.0 AS covered_hours,
  100.0 * SUM(CASE WHEN raw_fault = 1 AND streak_elapsed >= {{CONFIRM_SECONDS}} THEN held_seconds ELSE 0.0 END) / NULLIF(SUM(held_seconds), 0.0) AS fault_pct
FROM ranked
GROUP BY equipment_id;
```
{% endraw %}

### fcu_co2_damper.sql

`sql/fdd/postgres/rules/fcu_co2_damper.sql`

{% raw %}
```sql
-- PostgreSQL adaptation. Render numeric template parameters with render_rule.py.
-- Inputs must be scoped to one tenant/site and cadence; see README.md.
-- fcu_co2_damper.sql — first-class FCU screening rule
WITH normalized AS (
  SELECT equipment_id, timestamp_utc, sat, zone_t, zone_co2,
    CASE WHEN htg_valve_pct IS NULL THEN NULL WHEN htg_valve_pct > 1.0 THEN htg_valve_pct / 100.0 ELSE htg_valve_pct END AS htg,
    CASE WHEN clg_valve_pct IS NULL THEN NULL WHEN clg_valve_pct > 1.0 THEN clg_valve_pct / 100.0 ELSE clg_valve_pct END AS clg,
    CASE WHEN damper_cmd IS NULL THEN NULL WHEN damper_cmd > 1.0 THEN damper_cmd / 100.0 ELSE damper_cmd END AS dcmd,
    CASE WHEN damper_pct IS NULL THEN NULL WHEN damper_pct > 1.0 THEN damper_pct / 100.0 ELSE damper_pct END AS dpos,
    CASE
      WHEN fan_status IS NOT NULL THEN CASE WHEN fan_status > 0.05 THEN 1 ELSE 0 END
      WHEN fan_cmd IS NOT NULL THEN CASE WHEN (CASE WHEN fan_cmd > 1.0 THEN fan_cmd / 100.0 ELSE fan_cmd END) > 0.10 THEN 1 ELSE 0 END
      ELSE 0
    END AS fan_on
  FROM history
), base AS (
  SELECT equipment_id, timestamp_utc,
    CAST(CASE WHEN fan_on = 1 AND zone_co2 IS NOT NULL AND zone_co2 > {{CO2_HIGH_PPM}} AND zone_co2 >= 300.0 AND dcmd IS NOT NULL AND dcmd < {{DAMPER_LOW}} THEN 1 ELSE 0 END AS INT) AS raw_fault
  FROM normalized
), elapsed_hold AS (
  -- Forward sample-and-hold. A gap longer than MAX_GAP_HOURS is unknown:
  -- it is not fault time, not covered time, and it breaks confirmation.
  -- The last sample has no forward interval.
  SELECT
    stepped.*,
    CASE
      WHEN stepped.dt_seconds IS NULL
        OR stepped.dt_seconds <= 0.0
        OR stepped.dt_seconds > ({{MAX_GAP_HOURS}} * 3600.0)
      THEN 0.0
      ELSE stepped.dt_seconds
    END AS held_seconds,
    CASE
      WHEN stepped.dt_seconds > ({{MAX_GAP_HOURS}} * 3600.0) THEN 1
      ELSE 0
    END AS gap_after
  FROM (
    SELECT
      src.*,
      EXTRACT(EPOCH FROM (
        LEAD(src.timestamp_utc) OVER (
          PARTITION BY src.equipment_id ORDER BY src.timestamp_utc
        ) - src.timestamp_utc
      )) AS dt_seconds
    FROM base src
  ) stepped
),
lagged AS (
  SELECT
    *,
    CASE
      WHEN raw_fault = LAG(raw_fault) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc)
       AND COALESCE(LAG(gap_after) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc), 0) = 0
      THEN 0 ELSE 1
    END AS is_new_streak
  FROM elapsed_hold
), grouped AS (
  SELECT *, SUM(is_new_streak) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS UNBOUNDED PRECEDING) AS streak_id
  FROM lagged
), ranked AS (
  SELECT *, SUM(held_seconds) OVER (
      PARTITION BY equipment_id, streak_id ORDER BY timestamp_utc
      ROWS UNBOUNDED PRECEDING
    ) AS streak_elapsed
  FROM grouped
)
SELECT equipment_id,
  SUM(CASE WHEN raw_fault = 1 AND streak_elapsed >= {{CONFIRM_SECONDS}} THEN held_seconds ELSE 0.0 END) / 3600.0 AS fault_hours,
  SUM(held_seconds) / 3600.0 AS covered_hours,
  100.0 * SUM(CASE WHEN raw_fault = 1 AND streak_elapsed >= {{CONFIRM_SECONDS}} THEN held_seconds ELSE 0.0 END) / NULLIF(SUM(held_seconds), 0.0) AS fault_pct
FROM ranked
GROUP BY equipment_id;
```
{% endraw %}

### fcu_damper_pos.sql

`sql/fdd/postgres/rules/fcu_damper_pos.sql`

{% raw %}
```sql
-- PostgreSQL adaptation. Render numeric template parameters with render_rule.py.
-- Inputs must be scoped to one tenant/site and cadence; see README.md.
-- fcu_damper_pos.sql — first-class FCU screening rule
WITH normalized AS (
  SELECT equipment_id, timestamp_utc, sat, zone_t, zone_co2,
    CASE WHEN htg_valve_pct IS NULL THEN NULL WHEN htg_valve_pct > 1.0 THEN htg_valve_pct / 100.0 ELSE htg_valve_pct END AS htg,
    CASE WHEN clg_valve_pct IS NULL THEN NULL WHEN clg_valve_pct > 1.0 THEN clg_valve_pct / 100.0 ELSE clg_valve_pct END AS clg,
    CASE WHEN damper_cmd IS NULL THEN NULL WHEN damper_cmd > 1.0 THEN damper_cmd / 100.0 ELSE damper_cmd END AS dcmd,
    CASE WHEN damper_pct IS NULL THEN NULL WHEN damper_pct > 1.0 THEN damper_pct / 100.0 ELSE damper_pct END AS dpos,
    CASE
      WHEN fan_status IS NOT NULL THEN CASE WHEN fan_status > 0.05 THEN 1 ELSE 0 END
      WHEN fan_cmd IS NOT NULL THEN CASE WHEN (CASE WHEN fan_cmd > 1.0 THEN fan_cmd / 100.0 ELSE fan_cmd END) > 0.10 THEN 1 ELSE 0 END
      ELSE 0
    END AS fan_on
  FROM history
), base AS (
  SELECT equipment_id, timestamp_utc,
    CAST(CASE WHEN fan_on = 1 AND dcmd IS NOT NULL AND dpos IS NOT NULL AND dcmd >= {{COMMAND_MIN}} AND dcmd - dpos > {{POSITION_ERROR}} THEN 1 ELSE 0 END AS INT) AS raw_fault
  FROM normalized
), elapsed_hold AS (
  -- Forward sample-and-hold. A gap longer than MAX_GAP_HOURS is unknown:
  -- it is not fault time, not covered time, and it breaks confirmation.
  -- The last sample has no forward interval.
  SELECT
    stepped.*,
    CASE
      WHEN stepped.dt_seconds IS NULL
        OR stepped.dt_seconds <= 0.0
        OR stepped.dt_seconds > ({{MAX_GAP_HOURS}} * 3600.0)
      THEN 0.0
      ELSE stepped.dt_seconds
    END AS held_seconds,
    CASE
      WHEN stepped.dt_seconds > ({{MAX_GAP_HOURS}} * 3600.0) THEN 1
      ELSE 0
    END AS gap_after
  FROM (
    SELECT
      src.*,
      EXTRACT(EPOCH FROM (
        LEAD(src.timestamp_utc) OVER (
          PARTITION BY src.equipment_id ORDER BY src.timestamp_utc
        ) - src.timestamp_utc
      )) AS dt_seconds
    FROM base src
  ) stepped
),
lagged AS (
  SELECT
    *,
    CASE
      WHEN raw_fault = LAG(raw_fault) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc)
       AND COALESCE(LAG(gap_after) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc), 0) = 0
      THEN 0 ELSE 1
    END AS is_new_streak
  FROM elapsed_hold
), grouped AS (
  SELECT *, SUM(is_new_streak) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS UNBOUNDED PRECEDING) AS streak_id
  FROM lagged
), ranked AS (
  SELECT *, SUM(held_seconds) OVER (
      PARTITION BY equipment_id, streak_id ORDER BY timestamp_utc
      ROWS UNBOUNDED PRECEDING
    ) AS streak_elapsed
  FROM grouped
)
SELECT equipment_id,
  SUM(CASE WHEN raw_fault = 1 AND streak_elapsed >= {{CONFIRM_SECONDS}} THEN held_seconds ELSE 0.0 END) / 3600.0 AS fault_hours,
  SUM(held_seconds) / 3600.0 AS covered_hours,
  100.0 * SUM(CASE WHEN raw_fault = 1 AND streak_elapsed >= {{CONFIRM_SECONDS}} THEN held_seconds ELSE 0.0 END) / NULLIF(SUM(held_seconds), 0.0) AS fault_pct
FROM ranked
GROUP BY equipment_id;
```
{% endraw %}

### fcu_deadband.sql

`sql/fdd/postgres/rules/fcu_deadband.sql`

{% raw %}
```sql
-- PostgreSQL adaptation. Render numeric template parameters with render_rule.py.
-- Inputs must be scoped to one tenant/site and cadence; see README.md.
-- FCU-DEADBAND — pass-through FCU setpoints are normalized to °C.
-- Duration is the eligible forward delta, not a row count times poll.
WITH ordered AS (
  SELECT
    equipment_id,
    cooling_sp,
    heating_sp,
    EXTRACT(EPOCH FROM (
      LEAD(timestamp_utc) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc)
      - timestamp_utc
    )) AS dt_seconds
  FROM history
),
held AS (
  SELECT
    equipment_id,
    cooling_sp,
    heating_sp,
    CASE
      WHEN dt_seconds IS NULL OR dt_seconds <= 0.0 OR dt_seconds > ({{MAX_GAP_HOURS}} * 3600.0)
      THEN 0.0
      ELSE dt_seconds
    END AS held_seconds
  FROM ordered
)
SELECT
  equipment_id,
  SUM(CASE
    WHEN cooling_sp IS NOT NULL AND heating_sp IS NOT NULL
     AND cooling_sp - heating_sp < {{DEADBAND_C}}
    THEN held_seconds ELSE 0.0
  END) / 3600.0 AS fault_hours,
  SUM(held_seconds) / 3600.0 AS covered_hours,
  100.0 * SUM(CASE
    WHEN cooling_sp IS NOT NULL AND heating_sp IS NOT NULL
     AND cooling_sp - heating_sp < {{DEADBAND_C}}
    THEN held_seconds ELSE 0.0
  END) / NULLIF(SUM(held_seconds), 0.0) AS fault_pct
FROM held
GROUP BY equipment_id;
```
{% endraw %}

### fcu_htg_coil.sql

`sql/fdd/postgres/rules/fcu_htg_coil.sql`

{% raw %}
```sql
-- PostgreSQL adaptation. Render numeric template parameters with render_rule.py.
-- Inputs must be scoped to one tenant/site and cadence; see README.md.
-- fcu_htg_coil.sql — first-class FCU screening rule
WITH normalized AS (
  SELECT equipment_id, timestamp_utc, sat, zone_t, zone_co2,
    CASE WHEN htg_valve_pct IS NULL THEN NULL WHEN htg_valve_pct > 1.0 THEN htg_valve_pct / 100.0 ELSE htg_valve_pct END AS htg,
    CASE WHEN clg_valve_pct IS NULL THEN NULL WHEN clg_valve_pct > 1.0 THEN clg_valve_pct / 100.0 ELSE clg_valve_pct END AS clg,
    CASE WHEN damper_cmd IS NULL THEN NULL WHEN damper_cmd > 1.0 THEN damper_cmd / 100.0 ELSE damper_cmd END AS dcmd,
    CASE WHEN damper_pct IS NULL THEN NULL WHEN damper_pct > 1.0 THEN damper_pct / 100.0 ELSE damper_pct END AS dpos,
    CASE
      WHEN fan_status IS NOT NULL THEN CASE WHEN fan_status > 0.05 THEN 1 ELSE 0 END
      WHEN fan_cmd IS NOT NULL THEN CASE WHEN (CASE WHEN fan_cmd > 1.0 THEN fan_cmd / 100.0 ELSE fan_cmd END) > 0.10 THEN 1 ELSE 0 END
      ELSE 0
    END AS fan_on
  FROM history
), base AS (
  SELECT equipment_id, timestamp_utc,
    CAST(CASE WHEN sat IS NOT NULL AND zone_t IS NOT NULL AND fan_on = 1 AND htg >= {{VALVE_OPEN}} AND sat - zone_t < {{COIL_DELTA}} THEN 1 ELSE 0 END AS INT) AS raw_fault
  FROM normalized
), elapsed_hold AS (
  -- Forward sample-and-hold. A gap longer than MAX_GAP_HOURS is unknown:
  -- it is not fault time, not covered time, and it breaks confirmation.
  -- The last sample has no forward interval.
  SELECT
    stepped.*,
    CASE
      WHEN stepped.dt_seconds IS NULL
        OR stepped.dt_seconds <= 0.0
        OR stepped.dt_seconds > ({{MAX_GAP_HOURS}} * 3600.0)
      THEN 0.0
      ELSE stepped.dt_seconds
    END AS held_seconds,
    CASE
      WHEN stepped.dt_seconds > ({{MAX_GAP_HOURS}} * 3600.0) THEN 1
      ELSE 0
    END AS gap_after
  FROM (
    SELECT
      src.*,
      EXTRACT(EPOCH FROM (
        LEAD(src.timestamp_utc) OVER (
          PARTITION BY src.equipment_id ORDER BY src.timestamp_utc
        ) - src.timestamp_utc
      )) AS dt_seconds
    FROM base src
  ) stepped
),
lagged AS (
  SELECT
    *,
    CASE
      WHEN raw_fault = LAG(raw_fault) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc)
       AND COALESCE(LAG(gap_after) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc), 0) = 0
      THEN 0 ELSE 1
    END AS is_new_streak
  FROM elapsed_hold
), grouped AS (
  SELECT *, SUM(is_new_streak) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS UNBOUNDED PRECEDING) AS streak_id
  FROM lagged
), ranked AS (
  SELECT *, SUM(held_seconds) OVER (
      PARTITION BY equipment_id, streak_id ORDER BY timestamp_utc
      ROWS UNBOUNDED PRECEDING
    ) AS streak_elapsed
  FROM grouped
)
SELECT equipment_id,
  SUM(CASE WHEN raw_fault = 1 AND streak_elapsed >= {{CONFIRM_SECONDS}} THEN held_seconds ELSE 0.0 END) / 3600.0 AS fault_hours,
  SUM(held_seconds) / 3600.0 AS covered_hours,
  100.0 * SUM(CASE WHEN raw_fault = 1 AND streak_elapsed >= {{CONFIRM_SECONDS}} THEN held_seconds ELSE 0.0 END) / NULLIF(SUM(held_seconds), 0.0) AS fault_pct
FROM ranked
GROUP BY equipment_id;
```
{% endraw %}

### fcu_mode_cycle.sql

`sql/fdd/postgres/rules/fcu_mode_cycle.sql`

{% raw %}
```sql
-- PostgreSQL adaptation. Render numeric template parameters with render_rule.py.
-- Inputs must be scoped to one tenant/site and cadence; see README.md.
-- FCU-MODE-CYCLE — cumulative heat/cool mode transitions in the analysis window.
-- Hours are eligible forward deltas after the change count reaches MODE_CHANGES.
WITH modes AS (
  SELECT
    equipment_id,
    timestamp_utc,
    CASE
      WHEN clg_valve_pct IS NOT NULL AND (CASE WHEN clg_valve_pct > 1.0 THEN clg_valve_pct / 100.0 ELSE clg_valve_pct END) > {{MODE_VALVE_MIN}} THEN -1
      WHEN htg_valve_pct IS NOT NULL AND (CASE WHEN htg_valve_pct > 1.0 THEN htg_valve_pct / 100.0 ELSE htg_valve_pct END) > {{MODE_VALVE_MIN}} THEN 1
      ELSE 0
    END AS mode
  FROM history
),
active_modes AS (
  SELECT equipment_id, timestamp_utc, mode
  FROM modes
  WHERE mode <> 0
),
changes AS (
  SELECT
    equipment_id,
    timestamp_utc,
    mode,
    CASE
      WHEN LAG(mode) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc) IS NOT NULL
       AND mode <> LAG(mode) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc)
      THEN 1 ELSE 0
    END AS changed,
    EXTRACT(EPOCH FROM (
      LEAD(timestamp_utc) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc)
      - timestamp_utc
    )) AS dt_seconds
  FROM active_modes
),
cumulative AS (
  SELECT
    equipment_id,
    SUM(changed) OVER (
      PARTITION BY equipment_id ORDER BY timestamp_utc ROWS UNBOUNDED PRECEDING
    ) AS change_count,
    CASE
      WHEN dt_seconds IS NULL OR dt_seconds <= 0.0 OR dt_seconds > ({{MAX_GAP_HOURS}} * 3600.0)
      THEN 0.0
      ELSE dt_seconds
    END AS held_seconds
  FROM changes
)
SELECT
  equipment_id,
  SUM(CASE WHEN change_count >= {{MODE_CHANGES}} THEN held_seconds ELSE 0.0 END) / 3600.0 AS fault_hours,
  SUM(held_seconds) / 3600.0 AS covered_hours,
  100.0 * SUM(CASE WHEN change_count >= {{MODE_CHANGES}} THEN held_seconds ELSE 0.0 END)
    / NULLIF(SUM(held_seconds), 0.0) AS fault_pct
FROM cumulative
GROUP BY equipment_id;
```
{% endraw %}

### fcu_sensor_null.sql

`sql/fdd/postgres/rules/fcu_sensor_null.sql`

{% raw %}
```sql
-- PostgreSQL adaptation. Render numeric template parameters with render_rule.py.
-- Inputs must be scoped to one tenant/site and cadence; see README.md.
-- FCU-SENSOR-NULL — own zone setpoint exists while a mapped zone sensor is predominantly null.
-- The runner rewrites this file to zero hours when zone_t is absent from history.
-- Null time and eligible time are eligible forward deltas. A long gap is unknown.
WITH ordered AS (
  SELECT
    equipment_id,
    zone_air_temp_sp,
    zone_t,
    EXTRACT(EPOCH FROM (
      LEAD(timestamp_utc) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc)
      - timestamp_utc
    )) AS dt_seconds
  FROM history
),
held AS (
  SELECT
    equipment_id,
    zone_air_temp_sp,
    zone_t,
    CASE
      WHEN dt_seconds IS NULL OR dt_seconds <= 0.0 OR dt_seconds > ({{MAX_GAP_HOURS}} * 3600.0)
      THEN 0.0
      ELSE dt_seconds
    END AS held_seconds
  FROM ordered
),
coverage AS (
  SELECT
    equipment_id,
    SUM(CASE WHEN zone_air_temp_sp IS NOT NULL THEN held_seconds ELSE 0.0 END) AS eligible_seconds,
    SUM(CASE
      WHEN zone_air_temp_sp IS NOT NULL AND zone_t IS NULL THEN held_seconds
      ELSE 0.0
    END) AS null_seconds
  FROM held
  GROUP BY equipment_id
)
SELECT
  equipment_id,
  CASE
    WHEN eligible_seconds > 0.0
     AND null_seconds / eligible_seconds >= {{NULL_FRACTION}}
    THEN null_seconds / 3600.0
    ELSE 0.0
  END AS fault_hours,
  eligible_seconds / 3600.0 AS covered_hours,
  CASE
    WHEN eligible_seconds > 0.0
     AND null_seconds / eligible_seconds >= {{NULL_FRACTION}}
    THEN 100.0 * null_seconds / eligible_seconds
    ELSE 0.0
  END AS fault_pct
FROM coverage;
```
{% endraw %}

### fcu_valve_pass_clg.sql

`sql/fdd/postgres/rules/fcu_valve_pass_clg.sql`

{% raw %}
```sql
-- PostgreSQL adaptation. Render numeric template parameters with render_rule.py.
-- Inputs must be scoped to one tenant/site and cadence; see README.md.
-- fcu_valve_pass_clg.sql — first-class FCU screening rule
WITH normalized AS (
  SELECT equipment_id, timestamp_utc, sat, zone_t, zone_co2,
    CASE WHEN htg_valve_pct IS NULL THEN NULL WHEN htg_valve_pct > 1.0 THEN htg_valve_pct / 100.0 ELSE htg_valve_pct END AS htg,
    CASE WHEN clg_valve_pct IS NULL THEN NULL WHEN clg_valve_pct > 1.0 THEN clg_valve_pct / 100.0 ELSE clg_valve_pct END AS clg,
    CASE WHEN damper_cmd IS NULL THEN NULL WHEN damper_cmd > 1.0 THEN damper_cmd / 100.0 ELSE damper_cmd END AS dcmd,
    CASE WHEN damper_pct IS NULL THEN NULL WHEN damper_pct > 1.0 THEN damper_pct / 100.0 ELSE damper_pct END AS dpos,
    CASE
      WHEN fan_status IS NOT NULL THEN CASE WHEN fan_status > 0.05 THEN 1 ELSE 0 END
      WHEN fan_cmd IS NOT NULL THEN CASE WHEN (CASE WHEN fan_cmd > 1.0 THEN fan_cmd / 100.0 ELSE fan_cmd END) > 0.10 THEN 1 ELSE 0 END
      ELSE 0
    END AS fan_on
  FROM history
), base AS (
  SELECT equipment_id, timestamp_utc,
    CAST(CASE WHEN sat IS NOT NULL AND zone_t IS NOT NULL AND fan_on = 1 AND htg <= 0.05 AND clg <= 0.05 AND zone_t - sat > {{PASS_DELTA_F}} THEN 1 ELSE 0 END AS INT) AS raw_fault
  FROM normalized
), elapsed_hold AS (
  -- Forward sample-and-hold. A gap longer than MAX_GAP_HOURS is unknown:
  -- it is not fault time, not covered time, and it breaks confirmation.
  -- The last sample has no forward interval.
  SELECT
    stepped.*,
    CASE
      WHEN stepped.dt_seconds IS NULL
        OR stepped.dt_seconds <= 0.0
        OR stepped.dt_seconds > ({{MAX_GAP_HOURS}} * 3600.0)
      THEN 0.0
      ELSE stepped.dt_seconds
    END AS held_seconds,
    CASE
      WHEN stepped.dt_seconds > ({{MAX_GAP_HOURS}} * 3600.0) THEN 1
      ELSE 0
    END AS gap_after
  FROM (
    SELECT
      src.*,
      EXTRACT(EPOCH FROM (
        LEAD(src.timestamp_utc) OVER (
          PARTITION BY src.equipment_id ORDER BY src.timestamp_utc
        ) - src.timestamp_utc
      )) AS dt_seconds
    FROM base src
  ) stepped
),
lagged AS (
  SELECT
    *,
    CASE
      WHEN raw_fault = LAG(raw_fault) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc)
       AND COALESCE(LAG(gap_after) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc), 0) = 0
      THEN 0 ELSE 1
    END AS is_new_streak
  FROM elapsed_hold
), grouped AS (
  SELECT *, SUM(is_new_streak) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS UNBOUNDED PRECEDING) AS streak_id
  FROM lagged
), ranked AS (
  SELECT *, SUM(held_seconds) OVER (
      PARTITION BY equipment_id, streak_id ORDER BY timestamp_utc
      ROWS UNBOUNDED PRECEDING
    ) AS streak_elapsed
  FROM grouped
)
SELECT equipment_id,
  SUM(CASE WHEN raw_fault = 1 AND streak_elapsed >= {{CONFIRM_SECONDS}} THEN held_seconds ELSE 0.0 END) / 3600.0 AS fault_hours,
  SUM(held_seconds) / 3600.0 AS covered_hours,
  100.0 * SUM(CASE WHEN raw_fault = 1 AND streak_elapsed >= {{CONFIRM_SECONDS}} THEN held_seconds ELSE 0.0 END) / NULLIF(SUM(held_seconds), 0.0) AS fault_pct
FROM ranked
GROUP BY equipment_id;
```
{% endraw %}

### fcu_valve_pass_htg.sql

`sql/fdd/postgres/rules/fcu_valve_pass_htg.sql`

{% raw %}
```sql
-- PostgreSQL adaptation. Render numeric template parameters with render_rule.py.
-- Inputs must be scoped to one tenant/site and cadence; see README.md.
-- fcu_valve_pass_htg.sql — first-class FCU screening rule
WITH normalized AS (
  SELECT equipment_id, timestamp_utc, sat, zone_t, zone_co2,
    CASE WHEN htg_valve_pct IS NULL THEN NULL WHEN htg_valve_pct > 1.0 THEN htg_valve_pct / 100.0 ELSE htg_valve_pct END AS htg,
    CASE WHEN clg_valve_pct IS NULL THEN NULL WHEN clg_valve_pct > 1.0 THEN clg_valve_pct / 100.0 ELSE clg_valve_pct END AS clg,
    CASE WHEN damper_cmd IS NULL THEN NULL WHEN damper_cmd > 1.0 THEN damper_cmd / 100.0 ELSE damper_cmd END AS dcmd,
    CASE WHEN damper_pct IS NULL THEN NULL WHEN damper_pct > 1.0 THEN damper_pct / 100.0 ELSE damper_pct END AS dpos,
    CASE
      WHEN fan_status IS NOT NULL THEN CASE WHEN fan_status > 0.05 THEN 1 ELSE 0 END
      WHEN fan_cmd IS NOT NULL THEN CASE WHEN (CASE WHEN fan_cmd > 1.0 THEN fan_cmd / 100.0 ELSE fan_cmd END) > 0.10 THEN 1 ELSE 0 END
      ELSE 0
    END AS fan_on
  FROM history
), base AS (
  SELECT equipment_id, timestamp_utc,
    CAST(CASE WHEN sat IS NOT NULL AND zone_t IS NOT NULL AND fan_on = 1 AND htg <= 0.05 AND clg <= 0.05 AND sat - zone_t > {{PASS_DELTA_F}} THEN 1 ELSE 0 END AS INT) AS raw_fault
  FROM normalized
), elapsed_hold AS (
  -- Forward sample-and-hold. A gap longer than MAX_GAP_HOURS is unknown:
  -- it is not fault time, not covered time, and it breaks confirmation.
  -- The last sample has no forward interval.
  SELECT
    stepped.*,
    CASE
      WHEN stepped.dt_seconds IS NULL
        OR stepped.dt_seconds <= 0.0
        OR stepped.dt_seconds > ({{MAX_GAP_HOURS}} * 3600.0)
      THEN 0.0
      ELSE stepped.dt_seconds
    END AS held_seconds,
    CASE
      WHEN stepped.dt_seconds > ({{MAX_GAP_HOURS}} * 3600.0) THEN 1
      ELSE 0
    END AS gap_after
  FROM (
    SELECT
      src.*,
      EXTRACT(EPOCH FROM (
        LEAD(src.timestamp_utc) OVER (
          PARTITION BY src.equipment_id ORDER BY src.timestamp_utc
        ) - src.timestamp_utc
      )) AS dt_seconds
    FROM base src
  ) stepped
),
lagged AS (
  SELECT
    *,
    CASE
      WHEN raw_fault = LAG(raw_fault) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc)
       AND COALESCE(LAG(gap_after) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc), 0) = 0
      THEN 0 ELSE 1
    END AS is_new_streak
  FROM elapsed_hold
), grouped AS (
  SELECT *, SUM(is_new_streak) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS UNBOUNDED PRECEDING) AS streak_id
  FROM lagged
), ranked AS (
  SELECT *, SUM(held_seconds) OVER (
      PARTITION BY equipment_id, streak_id ORDER BY timestamp_utc
      ROWS UNBOUNDED PRECEDING
    ) AS streak_elapsed
  FROM grouped
)
SELECT equipment_id,
  SUM(CASE WHEN raw_fault = 1 AND streak_elapsed >= {{CONFIRM_SECONDS}} THEN held_seconds ELSE 0.0 END) / 3600.0 AS fault_hours,
  SUM(held_seconds) / 3600.0 AS covered_hours,
  100.0 * SUM(CASE WHEN raw_fault = 1 AND streak_elapsed >= {{CONFIRM_SECONDS}} THEN held_seconds ELSE 0.0 END) / NULLIF(SUM(held_seconds), 0.0) AS fault_pct
FROM ranked
GROUP BY equipment_id;
```
{% endraw %}

### hp1_discharge_cold.sql

`sql/fdd/postgres/rules/hp1_discharge_cold.sql`

{% raw %}
```sql
-- PostgreSQL adaptation. Render numeric template parameters with render_rule.py.
-- Inputs must be scoped to one tenant/site and cadence; see README.md.
-- hp1_discharge_cold.sql — Discharge cold when heating
WITH h AS (
  SELECT
    equipment_id,
    timestamp_utc,
    sat, zone_t,
    CASE WHEN fan_cmd IS NULL THEN NULL WHEN fan_cmd > 1.0 THEN fan_cmd / 100.0 ELSE fan_cmd END AS fan,
    compressor_status,
    fan_status,
    CASE
      WHEN compressor_status IS NOT NULL THEN CASE WHEN compressor_status > 0.05 THEN 1 ELSE 0 END
      WHEN fan_status IS NOT NULL THEN CASE WHEN fan_status > 0.05 THEN 1 ELSE 0 END
      WHEN fan_cmd IS NOT NULL THEN CASE WHEN (CASE WHEN fan_cmd > 1.0 THEN fan_cmd / 100.0 ELSE fan_cmd END) > 0.05 THEN 1 ELSE 0 END
      ELSE 1
    END AS proof_on

  FROM history
),
base AS (
  SELECT
    equipment_id,
    timestamp_utc,
    CAST(CASE
      WHEN COALESCE(proof_on, 0) = 0 THEN 0
      WHEN sat IS NULL OR zone_t IS NULL OR fan IS NULL THEN 0
      WHEN fan >= 0.05 AND zone_t < {{ZONE_COLD}} AND sat < {{MIN_SAT}} THEN 1
      ELSE 0
    END AS INT) AS raw_fault
  FROM h
),
elapsed_hold AS (
  -- Forward sample-and-hold. A gap longer than MAX_GAP_HOURS is unknown:
  -- it is not fault time, not covered time, and it breaks confirmation.
  -- The last sample has no forward interval.
  SELECT
    stepped.*,
    CASE
      WHEN stepped.dt_seconds IS NULL
        OR stepped.dt_seconds <= 0.0
        OR stepped.dt_seconds > ({{MAX_GAP_HOURS}} * 3600.0)
      THEN 0.0
      ELSE stepped.dt_seconds
    END AS held_seconds,
    CASE
      WHEN stepped.dt_seconds > ({{MAX_GAP_HOURS}} * 3600.0) THEN 1
      ELSE 0
    END AS gap_after
  FROM (
    SELECT
      src.*,
      EXTRACT(EPOCH FROM (
        LEAD(src.timestamp_utc) OVER (
          PARTITION BY src.equipment_id ORDER BY src.timestamp_utc
        ) - src.timestamp_utc
      )) AS dt_seconds
    FROM base src
  ) stepped
),
lagged AS (
  SELECT
    *,
    CASE
      WHEN raw_fault = LAG(raw_fault) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc)
       AND COALESCE(LAG(gap_after) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc), 0) = 0
      THEN 0 ELSE 1
    END AS is_new_streak
  FROM elapsed_hold
),
grp AS (
  SELECT
    *,
    SUM(is_new_streak)
      OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS UNBOUNDED PRECEDING) AS streak_id
  FROM lagged
),
ranked AS (
  SELECT
    *,
    SUM(held_seconds) OVER (
      PARTITION BY equipment_id, streak_id ORDER BY timestamp_utc
      ROWS UNBOUNDED PRECEDING
    ) AS streak_elapsed
  FROM grp
),
final AS (
  SELECT
    equipment_id,
    held_seconds,
    CASE WHEN raw_fault = 1 AND streak_elapsed >= {{CONFIRM_SECONDS}} THEN 1 ELSE 0 END AS confirmed
  FROM ranked
)
SELECT
  equipment_id,
  SUM(CASE WHEN confirmed = 1 THEN held_seconds ELSE 0.0 END) / 3600.0 AS fault_hours,
  SUM(held_seconds) / 3600.0 AS covered_hours,
  100.0 * SUM(CASE WHEN confirmed = 1 THEN held_seconds ELSE 0.0 END) / NULLIF(SUM(held_seconds), 0.0) AS fault_pct
FROM final
GROUP BY equipment_id;
```
{% endraw %}

### mech_oat_1.sql

`sql/fdd/postgres/rules/mech_oat_1.sql`

{% raw %}
```sql
-- PostgreSQL adaptation. Render numeric template parameters with render_rule.py.
-- Inputs must be scoped to one tenant/site and cadence; see README.md.
-- mech_oat_1.sql — Mechanical cooling below 15.555556°C web OAT
-- Proof: chiller_status OR cooling valve (pandas mechanical_proof_mask).
WITH h AS (
  SELECT
    equipment_id,
    timestamp_utc,
    web_oa_t,
    CASE WHEN clg_valve_pct IS NULL THEN NULL WHEN clg_valve_pct > 1.0 THEN clg_valve_pct / 100.0 ELSE clg_valve_pct END AS clg,
    CASE WHEN chiller_status IS NULL THEN NULL WHEN chiller_status > 0.05 THEN 1.0 ELSE 0.0 END AS chill_on
  FROM history
),
base AS (
  SELECT
    equipment_id,
    timestamp_utc,
    CAST(CASE
      WHEN web_oa_t IS NULL THEN 0
      WHEN web_oa_t >= {{MECH_OAT_MAX_F}} THEN 0
      WHEN chill_on IS NOT NULL AND chill_on > 0.05 THEN 1
      WHEN clg IS NOT NULL AND clg > 0.05 THEN 1
      ELSE 0
    END AS INT) AS raw_fault
  FROM h
),
elapsed_hold AS (
  -- Forward sample-and-hold. A gap longer than MAX_GAP_HOURS is unknown:
  -- it is not fault time, not covered time, and it breaks confirmation.
  -- The last sample has no forward interval.
  SELECT
    stepped.*,
    CASE
      WHEN stepped.dt_seconds IS NULL
        OR stepped.dt_seconds <= 0.0
        OR stepped.dt_seconds > ({{MAX_GAP_HOURS}} * 3600.0)
      THEN 0.0
      ELSE stepped.dt_seconds
    END AS held_seconds,
    CASE
      WHEN stepped.dt_seconds > ({{MAX_GAP_HOURS}} * 3600.0) THEN 1
      ELSE 0
    END AS gap_after
  FROM (
    SELECT
      src.*,
      EXTRACT(EPOCH FROM (
        LEAD(src.timestamp_utc) OVER (
          PARTITION BY src.equipment_id ORDER BY src.timestamp_utc
        ) - src.timestamp_utc
      )) AS dt_seconds
    FROM base src
  ) stepped
),
lagged AS (
  SELECT
    *,
    CASE
      WHEN raw_fault = LAG(raw_fault) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc)
       AND COALESCE(LAG(gap_after) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc), 0) = 0
      THEN 0 ELSE 1
    END AS is_new_streak
  FROM elapsed_hold
),
grp AS (
  SELECT
    *,
    SUM(is_new_streak)
      OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS UNBOUNDED PRECEDING) AS streak_id
  FROM lagged
),
ranked AS (
  SELECT
    *,
    SUM(held_seconds) OVER (
      PARTITION BY equipment_id, streak_id ORDER BY timestamp_utc
      ROWS UNBOUNDED PRECEDING
    ) AS streak_elapsed
  FROM grp
),
final AS (
  SELECT
    equipment_id,
    held_seconds,
    CASE WHEN raw_fault = 1 AND streak_elapsed >= {{CONFIRM_SECONDS}} THEN 1 ELSE 0 END AS confirmed
  FROM ranked
)
SELECT
  equipment_id,
  SUM(CASE WHEN confirmed = 1 THEN held_seconds ELSE 0.0 END) / 3600.0 AS fault_hours,
  SUM(held_seconds) / 3600.0 AS covered_hours,
  100.0 * SUM(CASE WHEN confirmed = 1 THEN held_seconds ELSE 0.0 END) / NULLIF(SUM(held_seconds), 0.0) AS fault_pct
FROM final
GROUP BY equipment_id;
```
{% endraw %}

### oa1_low_oa_frac.sql

`sql/fdd/postgres/rules/oa1_low_oa_frac.sql`

{% raw %}
```sql
-- PostgreSQL adaptation. Render numeric template parameters with render_rule.py.
-- Inputs must be scoped to one tenant/site and cadence; see README.md.
-- oa1_low_oa_frac.sql — Low OA fraction
WITH h AS (
  SELECT
    equipment_id,
    timestamp_utc,
    mat, rat, oa_t,
    CASE WHEN fan_cmd IS NULL THEN NULL WHEN fan_cmd > 1.0 THEN fan_cmd / 100.0 ELSE fan_cmd END AS fan,
    CASE
      WHEN fan_status IS NOT NULL THEN CASE WHEN fan_status > 0.05 THEN 1 ELSE 0 END
      WHEN fan_cmd IS NOT NULL THEN CASE WHEN (CASE WHEN fan_cmd > 1.0 THEN fan_cmd / 100.0 ELSE fan_cmd END) > 0.01 THEN 1 ELSE 0 END
      ELSE 1
    END AS fan_on

  FROM history
),
base AS (
  SELECT
    equipment_id,
    timestamp_utc,
    CAST(CASE
      WHEN COALESCE(fan_on, 1) = 0 THEN 0
      WHEN mat IS NULL OR rat IS NULL OR oa_t IS NULL THEN 0
      WHEN ABS(rat - oa_t) <= {{OAT_RAT_GUARD}} THEN 0
      WHEN (mat - rat) / NULLIF(oa_t - rat, 0) < {{MIN_OA_FRAC}}
       AND fan IS NOT NULL AND fan >= 0.05 THEN 1
      ELSE 0
    END AS INT) AS raw_fault
  FROM h
),
elapsed_hold AS (
  -- Forward sample-and-hold. A gap longer than MAX_GAP_HOURS is unknown:
  -- it is not fault time, not covered time, and it breaks confirmation.
  -- The last sample has no forward interval.
  SELECT
    stepped.*,
    CASE
      WHEN stepped.dt_seconds IS NULL
        OR stepped.dt_seconds <= 0.0
        OR stepped.dt_seconds > ({{MAX_GAP_HOURS}} * 3600.0)
      THEN 0.0
      ELSE stepped.dt_seconds
    END AS held_seconds,
    CASE
      WHEN stepped.dt_seconds > ({{MAX_GAP_HOURS}} * 3600.0) THEN 1
      ELSE 0
    END AS gap_after
  FROM (
    SELECT
      src.*,
      EXTRACT(EPOCH FROM (
        LEAD(src.timestamp_utc) OVER (
          PARTITION BY src.equipment_id ORDER BY src.timestamp_utc
        ) - src.timestamp_utc
      )) AS dt_seconds
    FROM base src
  ) stepped
),
lagged AS (
  SELECT
    *,
    CASE
      WHEN raw_fault = LAG(raw_fault) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc)
       AND COALESCE(LAG(gap_after) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc), 0) = 0
      THEN 0 ELSE 1
    END AS is_new_streak
  FROM elapsed_hold
),
grp AS (
  SELECT
    *,
    SUM(is_new_streak)
      OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS UNBOUNDED PRECEDING) AS streak_id
  FROM lagged
),
ranked AS (
  SELECT
    *,
    SUM(held_seconds) OVER (
      PARTITION BY equipment_id, streak_id ORDER BY timestamp_utc
      ROWS UNBOUNDED PRECEDING
    ) AS streak_elapsed
  FROM grp
),
final AS (
  SELECT
    equipment_id,
    held_seconds,
    CASE WHEN raw_fault = 1 AND streak_elapsed >= {{CONFIRM_SECONDS}} THEN 1 ELSE 0 END AS confirmed
  FROM ranked
)
SELECT
  equipment_id,
  SUM(CASE WHEN confirmed = 1 THEN held_seconds ELSE 0.0 END) / 3600.0 AS fault_hours,
  SUM(held_seconds) / 3600.0 AS covered_hours,
  100.0 * SUM(CASE WHEN confirmed = 1 THEN held_seconds ELSE 0.0 END) / NULLIF(SUM(held_seconds), 0.0) AS fault_pct
FROM final
GROUP BY equipment_id;
```
{% endraw %}

### oat_meteo_fault.sql

`sql/fdd/postgres/rules/oat_meteo_fault.sql`

{% raw %}
```sql
-- PostgreSQL adaptation. Render numeric template parameters with render_rule.py.
-- Inputs must be scoped to one tenant/site and cadence; see README.md.
-- oat_meteo_fault.sql — BAS OAT vs meteo reference (|Δ| > threshold) + confirm
-- Web weather is joined as-of: carry the last web sample forward up to
-- WEB_ASOF_BOUND_SECONDS (web cadence + margin from registry). Beyond that bound
-- the local sample is not compared (not-assessed seconds, never a no-fault).
-- Local oa_t uses primary_reference when set (engineer overlay); see docs/modeling/provider-point-overlay.md.
-- Prefer equipment web_oa_t (pandas); fall back to weather rows when absent.
-- Targeting is registry equipment_kinds (ahu) plus the package stamp applied
-- after this query. This file does not filter equipment_id by prefix or LIKE.
WITH wx AS (
  SELECT timestamp_utc, MAX(oa_t) AS wx_oa_t
  FROM weather
  WHERE oa_t IS NOT NULL
  GROUP BY timestamp_utc
),
joined AS (
  SELECT
    h.equipment_id,
    h.timestamp_utc,
    h.oa_t,
    COALESCE(h.web_oa_t, wx.wx_oa_t) AS ref_oa_t
  FROM history h
  LEFT JOIN wx
    ON h.timestamp_utc = wx.timestamp_utc
   AND h.web_oa_t IS NULL
),
base AS (
  SELECT
    equipment_id,
    timestamp_utc,
    CAST(CASE
      WHEN oa_t IS NOT NULL AND ref_oa_t IS NOT NULL AND ABS(oa_t - ref_oa_t) > {{OAT_ERR}}
      THEN 1 ELSE 0 END AS INT) AS raw_fault
  FROM joined
),
elapsed_hold AS (
  SELECT
    stepped.*,
    CASE
      WHEN stepped.dt_seconds IS NULL
        OR stepped.dt_seconds <= 0.0
        OR stepped.dt_seconds > ({{MAX_GAP_HOURS}} * 3600.0)
      THEN 0.0
      ELSE stepped.dt_seconds
    END AS held_seconds,
    CASE
      WHEN stepped.dt_seconds > ({{MAX_GAP_HOURS}} * 3600.0) THEN 1
      ELSE 0
    END AS gap_after
  FROM (
    SELECT
      src.*,
      EXTRACT(EPOCH FROM (
        LEAD(src.timestamp_utc) OVER (
          PARTITION BY src.equipment_id ORDER BY src.timestamp_utc
        ) - src.timestamp_utc
      )) AS dt_seconds
    FROM base src
  ) stepped
),
lagged AS (
  SELECT
    *,
    CASE
      WHEN raw_fault = LAG(raw_fault) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc)
       AND COALESCE(LAG(gap_after) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc), 0) = 0
      THEN 0 ELSE 1
    END AS is_new_streak
  FROM elapsed_hold
),
grp AS (
  SELECT
    *,
    SUM(is_new_streak)
      OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS UNBOUNDED PRECEDING) AS streak_id
  FROM lagged
),
ranked AS (
  SELECT
    *,
    SUM(held_seconds) OVER (
      PARTITION BY equipment_id, streak_id ORDER BY timestamp_utc
      ROWS UNBOUNDED PRECEDING
    ) AS streak_elapsed
  FROM grp
),
final AS (
  SELECT
    equipment_id,
    held_seconds,
    CASE WHEN raw_fault = 1 AND streak_elapsed >= {{CONFIRM_SECONDS}} THEN 1 ELSE 0 END AS confirmed
  FROM ranked
)
SELECT
  equipment_id,
  SUM(CASE WHEN confirmed = 1 THEN held_seconds ELSE 0.0 END) / 3600.0 AS fault_hours,
  SUM(held_seconds) / 3600.0 AS covered_hours,
  100.0 * SUM(CASE WHEN confirmed = 1 THEN held_seconds ELSE 0.0 END) / NULLIF(SUM(held_seconds), 0.0) AS fault_pct
FROM final
GROUP BY equipment_id;
```
{% endraw %}

### pid_hunt_1.sql

`sql/fdd/postgres/rules/pid_hunt_1.sql`

{% raw %}
```sql
-- PostgreSQL adaptation. Render numeric template parameters with render_rule.py.
-- Inputs must be scoped to one tenant/site and cadence; see README.md.
-- pid_hunt_1.sql — Suspected control-output hunting (rolling 1h metrics)
-- Matches pandas hunting_fault_mask: TV / span / cycles / reversals over
-- WINDOW_HOURS. The detection window is still a row frame (WINDOW_ROWS).
-- Fault hours integrate eligible forward deltas and do not add a phantom
-- interval after the last sample. {{WINDOW_ROWS}} / {{WINDOW_ROWS_PRECEDING}}
-- are derived from WINDOW_HOURS + POLL_SECONDS (literal ROWS bounds).
WITH h AS (
  SELECT
    equipment_id,
    timestamp_utc,
    CASE
      WHEN oa_damper_pct IS NOT NULL THEN
        CASE WHEN oa_damper_pct > 1.0 THEN oa_damper_pct ELSE oa_damper_pct * 100.0 END
      WHEN clg_valve_pct IS NOT NULL THEN
        CASE WHEN clg_valve_pct > 1.0 THEN clg_valve_pct ELSE clg_valve_pct * 100.0 END
      WHEN htg_valve_pct IS NOT NULL THEN
        CASE WHEN htg_valve_pct > 1.0 THEN htg_valve_pct ELSE htg_valve_pct * 100.0 END
      WHEN damper_pct IS NOT NULL THEN
        CASE WHEN damper_pct > 1.0 THEN damper_pct ELSE damper_pct * 100.0 END
      ELSE NULL
    END AS out_pct,
    LAG(
      CASE
        WHEN oa_damper_pct IS NOT NULL THEN
          CASE WHEN oa_damper_pct > 1.0 THEN oa_damper_pct ELSE oa_damper_pct * 100.0 END
        WHEN clg_valve_pct IS NOT NULL THEN
          CASE WHEN clg_valve_pct > 1.0 THEN clg_valve_pct ELSE clg_valve_pct * 100.0 END
        WHEN htg_valve_pct IS NOT NULL THEN
          CASE WHEN htg_valve_pct > 1.0 THEN htg_valve_pct ELSE htg_valve_pct * 100.0 END
        WHEN damper_pct IS NOT NULL THEN
          CASE WHEN damper_pct > 1.0 THEN damper_pct ELSE damper_pct * 100.0 END
        ELSE NULL
      END
    ) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc) AS prev_out,
    COALESCE(loop_enabled, 1.0) AS loop_on,
    CASE
      WHEN fan_status IS NOT NULL THEN CASE WHEN fan_status > 0.05 THEN 1 ELSE 0 END
      WHEN fan_cmd IS NOT NULL THEN CASE WHEN (CASE WHEN fan_cmd > 1.0 THEN fan_cmd / 100.0 ELSE fan_cmd END) > 0.01 THEN 1 ELSE 0 END
      ELSE 1
    END AS fan_on
  FROM history
),
deltas AS (
  SELECT
    *,
    CASE
      WHEN prev_out IS NULL OR out_pct IS NULL THEN NULL
      WHEN ABS(out_pct - prev_out) >= {{CHANGE_DEADBAND_PCT}} THEN out_pct - prev_out
      ELSE 0.0
    END AS sig_delta
  FROM h
),
steps AS (
  SELECT
    *,
    CASE
      WHEN sig_delta IS NULL THEN 0
      ELSE ABS(sig_delta)
    END AS abs_step,
    CASE
      WHEN sig_delta IS NULL OR sig_delta = 0 THEN 0
      WHEN LAG(sig_delta) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc) IS NULL THEN 0
      WHEN LAG(sig_delta) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc) = 0 THEN 0
      WHEN sig_delta * LAG(sig_delta) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc) < 0 THEN 1
      ELSE 0
    END AS reversal_event
  FROM deltas
),
win AS (
  SELECT
    equipment_id,
    timestamp_utc,
    out_pct,
    fan_on,
    loop_on,
    COUNT(out_pct) OVER (
      PARTITION BY equipment_id ORDER BY timestamp_utc
      ROWS BETWEEN {{WINDOW_ROWS_PRECEDING}} PRECEDING AND CURRENT ROW
    ) AS n_samples,
    SUM(abs_step) OVER (
      PARTITION BY equipment_id ORDER BY timestamp_utc
      ROWS BETWEEN {{WINDOW_ROWS_PRECEDING}} PRECEDING AND CURRENT ROW
    ) AS tv,
    MAX(out_pct) OVER (
      PARTITION BY equipment_id ORDER BY timestamp_utc
      ROWS BETWEEN {{WINDOW_ROWS_PRECEDING}} PRECEDING AND CURRENT ROW
    )
      - MIN(out_pct) OVER (
      PARTITION BY equipment_id ORDER BY timestamp_utc
      ROWS BETWEEN {{WINDOW_ROWS_PRECEDING}} PRECEDING AND CURRENT ROW
    ) AS span,
    SUM(reversal_event) OVER (
      PARTITION BY equipment_id ORDER BY timestamp_utc
      ROWS BETWEEN {{WINDOW_ROWS_PRECEDING}} PRECEDING AND CURRENT ROW
    ) AS reversals
  FROM steps
),
base AS (
  SELECT
    equipment_id,
    timestamp_utc,
    CAST(CASE
      WHEN COALESCE(fan_on, 0) = 0 THEN 0
      WHEN loop_on IS NOT NULL AND loop_on <= 0.05 THEN 0
      WHEN out_pct IS NULL THEN 0
      WHEN n_samples < CAST(CEIL({{WINDOW_ROWS}} * {{MINIMUM_COVERAGE_PCT}} / 100.0) AS INT) THEN 0
      WHEN span < {{MINIMUM_SPAN_PCT}} THEN 0
      WHEN tv < {{TOTAL_VARIATION_FAULT_PCT}} THEN 0
      WHEN span <= 0 THEN 0
      WHEN (tv / (2.0 * NULLIF(span, 0))) < {{MINIMUM_EQUIVALENT_CYCLES}} THEN 0
      WHEN reversals < {{MINIMUM_REVERSALS}} THEN 0
      ELSE 1
    END AS INT) AS raw_fault
  FROM win
),
elapsed_hold AS (
  -- Forward sample-and-hold. A gap longer than MAX_GAP_HOURS is unknown:
  -- it is not fault time, not covered time, and it breaks confirmation.
  -- The last sample has no forward interval.
  SELECT
    stepped.*,
    CASE
      WHEN stepped.dt_seconds IS NULL
        OR stepped.dt_seconds <= 0.0
        OR stepped.dt_seconds > ({{MAX_GAP_HOURS}} * 3600.0)
      THEN 0.0
      ELSE stepped.dt_seconds
    END AS held_seconds,
    CASE
      WHEN stepped.dt_seconds > ({{MAX_GAP_HOURS}} * 3600.0) THEN 1
      ELSE 0
    END AS gap_after
  FROM (
    SELECT
      src.*,
      EXTRACT(EPOCH FROM (
        LEAD(src.timestamp_utc) OVER (
          PARTITION BY src.equipment_id ORDER BY src.timestamp_utc
        ) - src.timestamp_utc
      )) AS dt_seconds
    FROM base src
  ) stepped
),
lagged AS (
  SELECT
    *,
    CASE
      WHEN raw_fault = LAG(raw_fault) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc)
       AND COALESCE(LAG(gap_after) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc), 0) = 0
      THEN 0 ELSE 1
    END AS is_new_streak
  FROM elapsed_hold
),
grp AS (
  SELECT
    *,
    SUM(is_new_streak)
      OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS UNBOUNDED PRECEDING) AS streak_id
  FROM lagged
),
ranked AS (
  SELECT
    *,
    SUM(held_seconds) OVER (
      PARTITION BY equipment_id, streak_id ORDER BY timestamp_utc
      ROWS UNBOUNDED PRECEDING
    ) AS streak_elapsed
  FROM grp
),
final AS (
  SELECT
    equipment_id,
    held_seconds,
    CASE WHEN raw_fault = 1 AND streak_elapsed >= {{CONFIRM_SECONDS}} THEN 1 ELSE 0 END AS confirmed
  FROM ranked
)
SELECT
  equipment_id,
  SUM(CASE WHEN confirmed = 1 THEN held_seconds ELSE 0.0 END) / 3600.0 AS fault_hours,
  SUM(held_seconds) / 3600.0 AS covered_hours,
  100.0 * SUM(CASE WHEN confirmed = 1 THEN held_seconds ELSE 0.0 END) / NULLIF(SUM(held_seconds), 0.0) AS fault_pct
FROM final
GROUP BY equipment_id;
```
{% endraw %}

### reset1_sat_oa_reset.sql

`sql/fdd/postgres/rules/reset1_sat_oa_reset.sql`

{% raw %}
```sql
-- PostgreSQL adaptation. Render numeric template parameters with render_rule.py.
-- Inputs must be scoped to one tenant/site and cadence; see README.md.
-- reset1_sat_oa_reset.sql — SAT SP not tracking OA reset curve
-- expected = RESET_SAT_AT_65 + RESET_SLOPE * (oa_t - RESET_OAT_REF)
WITH h AS (
  SELECT
    equipment_id,
    timestamp_utc,
    sat_sp,
    oa_t,
    CASE
      WHEN fan_status IS NOT NULL THEN CASE WHEN fan_status > 0.05 THEN 1 ELSE 0 END
      WHEN fan_cmd IS NOT NULL THEN CASE WHEN (CASE WHEN fan_cmd > 1.0 THEN fan_cmd / 100.0 ELSE fan_cmd END) > 0.05 THEN 1 ELSE 0 END
      ELSE 1
    END AS fan_on
  FROM history
),
base AS (
  SELECT
    equipment_id,
    timestamp_utc,
    CAST(CASE
      WHEN COALESCE(fan_on, 0) = 0 THEN 0
      WHEN sat_sp IS NULL OR oa_t IS NULL THEN 0
      WHEN abs(sat_sp - ({{RESET_SAT_AT_65}} + {{RESET_SLOPE}} * (oa_t - {{RESET_OAT_REF}}))) > {{RESET_ERR_F}} THEN 1
      ELSE 0
    END AS INT) AS raw_fault
  FROM h
),
elapsed_hold AS (
  -- Forward sample-and-hold. A gap longer than MAX_GAP_HOURS is unknown:
  -- it is not fault time, not covered time, and it breaks confirmation.
  -- The last sample has no forward interval.
  SELECT
    stepped.*,
    CASE
      WHEN stepped.dt_seconds IS NULL
        OR stepped.dt_seconds <= 0.0
        OR stepped.dt_seconds > ({{MAX_GAP_HOURS}} * 3600.0)
      THEN 0.0
      ELSE stepped.dt_seconds
    END AS held_seconds,
    CASE
      WHEN stepped.dt_seconds > ({{MAX_GAP_HOURS}} * 3600.0) THEN 1
      ELSE 0
    END AS gap_after
  FROM (
    SELECT
      src.*,
      EXTRACT(EPOCH FROM (
        LEAD(src.timestamp_utc) OVER (
          PARTITION BY src.equipment_id ORDER BY src.timestamp_utc
        ) - src.timestamp_utc
      )) AS dt_seconds
    FROM base src
  ) stepped
),
lagged AS (
  SELECT
    *,
    CASE
      WHEN raw_fault = LAG(raw_fault) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc)
       AND COALESCE(LAG(gap_after) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc), 0) = 0
      THEN 0 ELSE 1
    END AS is_new_streak
  FROM elapsed_hold
),
grp AS (
  SELECT
    *,
    SUM(is_new_streak)
      OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS UNBOUNDED PRECEDING) AS streak_id
  FROM lagged
),
ranked AS (
  SELECT
    *,
    SUM(held_seconds) OVER (
      PARTITION BY equipment_id, streak_id ORDER BY timestamp_utc
      ROWS UNBOUNDED PRECEDING
    ) AS streak_elapsed
  FROM grp
),
final AS (
  SELECT
    equipment_id,
    held_seconds,
    CASE WHEN raw_fault = 1 AND streak_elapsed >= {{CONFIRM_SECONDS}} THEN 1 ELSE 0 END AS confirmed
  FROM ranked
)
SELECT
  equipment_id,
  SUM(CASE WHEN confirmed = 1 THEN held_seconds ELSE 0.0 END) / 3600.0 AS fault_hours,
  SUM(held_seconds) / 3600.0 AS covered_hours,
  100.0 * SUM(CASE WHEN confirmed = 1 THEN held_seconds ELSE 0.0 END) / NULLIF(SUM(held_seconds), 0.0) AS fault_pct
FROM final
GROUP BY equipment_id;
```
{% endraw %}

### sat_high_fault.sql

`sql/fdd/postgres/rules/sat_high_fault.sql`

{% raw %}
```sql
-- PostgreSQL adaptation. Render numeric template parameters with render_rule.py.
-- Inputs must be scoped to one tenant/site and cadence; see README.md.
-- sat_high_fault.sql — FC13 SAT above SP at full cooling + confirm (matches cookbook fc13)
WITH h AS (
  SELECT
    equipment_id,
    timestamp_utc,
    sat,
    sat_sp,
    COALESCE(CASE WHEN clg_valve_pct IS NULL THEN NULL WHEN clg_valve_pct > 1.0 THEN clg_valve_pct / 100.0 ELSE clg_valve_pct END, 0.0) AS clg_valve_pct,
    COALESCE(CASE WHEN oa_damper_pct IS NULL THEN NULL WHEN oa_damper_pct > 1.0 THEN oa_damper_pct / 100.0 ELSE oa_damper_pct END, 0.0) AS oa_damper_pct,
    fan_cmd,
    fan_status,
        CASE
      WHEN {{REQUIRE_OPERATIONAL_GATE}} < 0.5 THEN 1
      WHEN fan_status IS NOT NULL THEN CASE WHEN fan_status > 0.05 THEN 1 ELSE 0 END
      WHEN fan_cmd IS NOT NULL THEN CASE WHEN (CASE WHEN fan_cmd > 1.0 THEN fan_cmd / 100.0 ELSE fan_cmd END) > {{FAN_ON_MIN}} THEN 1 ELSE 0 END
      ELSE 1
    END AS fan_on

  FROM history
),
base AS (
  SELECT
    equipment_id,
    timestamp_utc,
    CAST(CASE
      WHEN COALESCE(fan_on, 1) = 0 THEN 0
      WHEN COALESCE(mode_stable, 1) = 0 THEN 0
      WHEN sat IS NOT NULL AND sat_sp IS NOT NULL
       AND clg_valve_pct > {{CLG_FULL_MIN}}
       AND sat > sat_sp + {{EPS_SAT}}
       AND (oa_damper_pct <= {{OA_DAMPER_ECON_LOW}} OR oa_damper_pct > {{ECON_FULL_OPEN}})
      THEN 1 ELSE 0 END AS INT) AS raw_fault
  FROM (
  SELECT h.*,
    CASE
      WHEN COALESCE(fan_on, 1) = 0 THEN 0
      WHEN SUM(CASE WHEN COALESCE(fan_on, 1) = 0 THEN 1 ELSE 0 END) OVER (
        PARTITION BY equipment_id ORDER BY timestamp_utc
        ROWS BETWEEN {{MODE_DELAY_ROWS_PRECEDING}} PRECEDING AND CURRENT ROW
      ) = 0 THEN 1
      ELSE 0
    END AS mode_stable
  FROM h
) h
),
elapsed_hold AS (
  -- Forward sample-and-hold. A gap longer than MAX_GAP_HOURS is unknown:
  -- it is not fault time, not covered time, and it breaks confirmation.
  -- The last sample has no forward interval.
  SELECT
    stepped.*,
    CASE
      WHEN stepped.dt_seconds IS NULL
        OR stepped.dt_seconds <= 0.0
        OR stepped.dt_seconds > ({{MAX_GAP_HOURS}} * 3600.0)
      THEN 0.0
      ELSE stepped.dt_seconds
    END AS held_seconds,
    CASE
      WHEN stepped.dt_seconds > ({{MAX_GAP_HOURS}} * 3600.0) THEN 1
      ELSE 0
    END AS gap_after
  FROM (
    SELECT
      src.*,
      EXTRACT(EPOCH FROM (
        LEAD(src.timestamp_utc) OVER (
          PARTITION BY src.equipment_id ORDER BY src.timestamp_utc
        ) - src.timestamp_utc
      )) AS dt_seconds
    FROM base src
  ) stepped
),
lagged AS (
  SELECT
    *,
    CASE
      WHEN raw_fault = LAG(raw_fault) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc)
       AND COALESCE(LAG(gap_after) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc), 0) = 0
      THEN 0 ELSE 1
    END AS is_new_streak
  FROM elapsed_hold
),
grp AS (
  SELECT
    *,
    SUM(is_new_streak)
      OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS UNBOUNDED PRECEDING) AS streak_id
  FROM lagged
),
ranked AS (
  SELECT
    *,
    SUM(held_seconds) OVER (
      PARTITION BY equipment_id, streak_id ORDER BY timestamp_utc
      ROWS UNBOUNDED PRECEDING
    ) AS streak_elapsed
  FROM grp
),
final AS (
  SELECT
    equipment_id,
    held_seconds,
    CASE WHEN raw_fault = 1 AND streak_elapsed >= {{CONFIRM_SECONDS}} THEN 1 ELSE 0 END AS confirmed
  FROM ranked
)
, cov AS (
  SELECT equipment_id,
    100.0 * AVG(CAST(COALESCE(fan_on, 1) AS DOUBLE PRECISION)) AS cov_pct
  FROM h
  GROUP BY equipment_id
)
SELECT
  f.equipment_id,
  CASE
    WHEN {{REQUIRE_OPERATIONAL_GATE}} < 0.5 THEN SUM(CASE WHEN f.confirmed = 1 THEN f.held_seconds ELSE 0.0 END) / 3600.0
    WHEN MAX(c.cov_pct) < {{MINIMUM_ACTIVE_COVERAGE_PCT}} THEN 0.0
    ELSE SUM(CASE WHEN f.confirmed = 1 THEN f.held_seconds ELSE 0.0 END) / 3600.0
  END AS fault_hours,
  SUM(f.held_seconds) / 3600.0 AS covered_hours,
  CASE
    WHEN {{REQUIRE_OPERATIONAL_GATE}} < 0.5 THEN 100.0 * SUM(CASE WHEN f.confirmed = 1 THEN f.held_seconds ELSE 0.0 END) / NULLIF(SUM(f.held_seconds), 0.0)
    WHEN MAX(c.cov_pct) < {{MINIMUM_ACTIVE_COVERAGE_PCT}} THEN 0.0
    ELSE 100.0 * SUM(CASE WHEN f.confirmed = 1 THEN f.held_seconds ELSE 0.0 END) / NULLIF(SUM(f.held_seconds), 0.0)
  END AS fault_pct
FROM final f
LEFT JOIN cov c ON f.equipment_id = c.equipment_id
GROUP BY f.equipment_id;
```
{% endraw %}

### sched1_unoccupied_runtime.sql

`sql/fdd/postgres/rules/sched1_unoccupied_runtime.sql`

{% raw %}
```sql
-- PostgreSQL adaptation. Render numeric template parameters with render_rule.py.
-- Inputs must be scoped to one tenant/site and cadence; see README.md.
-- sched1_unoccupied_runtime.sql — Excess / wasted unoccupied runtime
-- Pandas sched1: unoccupied & fan_on; when zone_t mapped, also require comfort band
-- (zone already satisfied → optimal-start / bad schedule signal).
-- When zone_t is absent from history, the runner injects NULL zone_t (optional role)
-- so behavior matches pandas “no zone → base only”.
-- Portable occupancy: literal 'unoccupied' OR numeric/boolean falsey (0 / 0.0 / false).
WITH base AS (
  SELECT
    equipment_id,
    timestamp_utc,
        CAST(CASE
          WHEN occ_mode IS NULL OR fan_status IS NULL THEN 0
          WHEN fan_status > 0.5
            AND (
              LOWER(trim(CAST(occ_mode AS VARCHAR))) IN
                ('unoccupied','unocc','off','false','night','standby','setback','no')
              OR (
                fdd.try_double(trim(CAST(occ_mode AS VARCHAR))) IS NOT NULL
                AND fdd.try_double(trim(CAST(occ_mode AS VARCHAR))) <= 0.05
              )
            )
            AND (
              zone_t IS NULL
              OR (zone_t >= {{ZONE_T_LO}} AND zone_t <= {{ZONE_T_HI}})
            )
          THEN 1
          ELSE 0
        END AS INT) AS raw_fault
  FROM history
),
elapsed_hold AS (
  -- Forward sample-and-hold. A gap longer than MAX_GAP_HOURS is unknown:
  -- it is not fault time, not covered time, and it breaks confirmation.
  -- The last sample has no forward interval.
  SELECT
    stepped.*,
    CASE
      WHEN stepped.dt_seconds IS NULL
        OR stepped.dt_seconds <= 0.0
        OR stepped.dt_seconds > ({{MAX_GAP_HOURS}} * 3600.0)
      THEN 0.0
      ELSE stepped.dt_seconds
    END AS held_seconds,
    CASE
      WHEN stepped.dt_seconds > ({{MAX_GAP_HOURS}} * 3600.0) THEN 1
      ELSE 0
    END AS gap_after
  FROM (
    SELECT
      src.*,
      EXTRACT(EPOCH FROM (
        LEAD(src.timestamp_utc) OVER (
          PARTITION BY src.equipment_id ORDER BY src.timestamp_utc
        ) - src.timestamp_utc
      )) AS dt_seconds
    FROM base src
  ) stepped
),
lagged AS (
  SELECT
    *,
    CASE
      WHEN raw_fault = LAG(raw_fault) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc)
       AND COALESCE(LAG(gap_after) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc), 0) = 0
      THEN 0 ELSE 1
    END AS is_new_streak
  FROM elapsed_hold
),
grp AS (
  SELECT
    *,
    SUM(is_new_streak)
      OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS UNBOUNDED PRECEDING) AS streak_id
  FROM lagged
),
ranked AS (
  SELECT
    *,
    SUM(held_seconds) OVER (
      PARTITION BY equipment_id, streak_id ORDER BY timestamp_utc
      ROWS UNBOUNDED PRECEDING
    ) AS streak_elapsed
  FROM grp
),
final AS (
  SELECT
    equipment_id,
    held_seconds,
    CASE WHEN raw_fault = 1 AND streak_elapsed >= {{CONFIRM_SECONDS}} THEN 1 ELSE 0 END AS confirmed
  FROM ranked
)
SELECT
  equipment_id,
  SUM(CASE WHEN confirmed = 1 THEN held_seconds ELSE 0.0 END) / 3600.0 AS fault_hours,
  SUM(held_seconds) / 3600.0 AS covered_hours,
  100.0 * SUM(CASE WHEN confirmed = 1 THEN held_seconds ELSE 0.0 END) / NULLIF(SUM(held_seconds), 0.0) AS fault_pct
FROM final
GROUP BY equipment_id;
```
{% endraw %}

### sched247_always_on.sql

`sql/fdd/postgres/rules/sched247_always_on.sql`

{% raw %}
```sql
-- PostgreSQL adaptation. Render numeric template parameters with render_rule.py.
-- Inputs must be scoped to one tenant/site and cadence; see README.md.
-- sched247_always_on.sql — Always-on fan or pump runtime
-- Pandas `_sched247`: ranked proof (status > command), then FAULT only when
-- mean(on) >= always_on_pct over the whole analysis window. Confirmed hours
-- are the on-mask after that gate (not a streak-only screen).
-- Pressure is not used for the FAULT mask (4.3 migration).
WITH h AS (
  SELECT
    equipment_id,
    timestamp_utc,
    fan_status,
    pump_status,
    chiller_status,
    CASE WHEN fan_cmd IS NULL THEN NULL WHEN fan_cmd > 1.0 THEN fan_cmd / 100.0 ELSE fan_cmd END AS fan
  FROM history
),
proof AS (
  SELECT
    equipment_id,
    timestamp_utc,
    CAST(CASE
      WHEN fan_status IS NOT NULL THEN CASE WHEN fan_status > 0.05 THEN 1 ELSE 0 END
      WHEN pump_status IS NOT NULL THEN CASE WHEN pump_status > 0.05 THEN 1 ELSE 0 END
      WHEN chiller_status IS NOT NULL THEN CASE WHEN chiller_status > 0.05 THEN 1 ELSE 0 END
      WHEN fan IS NOT NULL THEN CASE WHEN fan >= 0.05 THEN 1 ELSE 0 END
      ELSE 0
    END AS INT) AS on_bit
  FROM h
),
win AS (
  SELECT
    equipment_id,
    timestamp_utc,
    on_bit,
    AVG(CAST(on_bit AS DOUBLE PRECISION)) OVER (PARTITION BY equipment_id) AS on_frac
  FROM proof
),
base AS (
  SELECT
    equipment_id,
    timestamp_utc,
    CAST(CASE
      WHEN on_frac >= {{ALWAYS_ON_PCT}} AND on_bit = 1 THEN 1
      ELSE 0
    END AS INT) AS raw_fault
  FROM win
),
elapsed_hold AS (
  -- Forward sample-and-hold. A gap longer than MAX_GAP_HOURS is unknown:
  -- it is not fault time, not covered time, and it breaks confirmation.
  -- The last sample has no forward interval.
  SELECT
    stepped.*,
    CASE
      WHEN stepped.dt_seconds IS NULL
        OR stepped.dt_seconds <= 0.0
        OR stepped.dt_seconds > ({{MAX_GAP_HOURS}} * 3600.0)
      THEN 0.0
      ELSE stepped.dt_seconds
    END AS held_seconds,
    CASE
      WHEN stepped.dt_seconds > ({{MAX_GAP_HOURS}} * 3600.0) THEN 1
      ELSE 0
    END AS gap_after
  FROM (
    SELECT
      src.*,
      EXTRACT(EPOCH FROM (
        LEAD(src.timestamp_utc) OVER (
          PARTITION BY src.equipment_id ORDER BY src.timestamp_utc
        ) - src.timestamp_utc
      )) AS dt_seconds
    FROM base src
  ) stepped
),
lagged AS (
  SELECT
    *,
    CASE
      WHEN raw_fault = LAG(raw_fault) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc)
       AND COALESCE(LAG(gap_after) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc), 0) = 0
      THEN 0 ELSE 1
    END AS is_new_streak
  FROM elapsed_hold
),
grp AS (
  SELECT
    *,
    SUM(is_new_streak)
      OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS UNBOUNDED PRECEDING) AS streak_id
  FROM lagged
),
ranked AS (
  SELECT
    *,
    SUM(held_seconds) OVER (
      PARTITION BY equipment_id, streak_id ORDER BY timestamp_utc
      ROWS UNBOUNDED PRECEDING
    ) AS streak_elapsed
  FROM grp
),
final AS (
  SELECT
    equipment_id,
    held_seconds,
    CASE WHEN raw_fault = 1 AND streak_elapsed >= {{CONFIRM_SECONDS}} THEN 1 ELSE 0 END AS confirmed
  FROM ranked
)
SELECT
  equipment_id,
  SUM(CASE WHEN confirmed = 1 THEN held_seconds ELSE 0.0 END) / 3600.0 AS fault_hours,
  SUM(held_seconds) / 3600.0 AS covered_hours,
  100.0 * SUM(CASE WHEN confirmed = 1 THEN held_seconds ELSE 0.0 END) / NULLIF(SUM(held_seconds), 0.0) AS fault_pct
FROM final
GROUP BY equipment_id;
```
{% endraw %}

### sv_flatline.sql

`sql/fdd/postgres/rules/sv_flatline.sql`

{% raw %}
```sql
-- PostgreSQL adaptation. Render numeric template parameters with render_rule.py.
-- Inputs must be scoped to one tenant/site and cadence; see README.md.
-- sv_flatline.sql — Sensor flatline (stuck) — pandas FLATLINE_SENSOR_ROLES catalog
-- Temperature/humidity analogs (SENSOR_LIMITS minus duct static). Faults when ANY
-- mapped role is flat while the equipment is energized.
-- {{FLATLINE_ROWS}} / {{FLATLINE_ROWS_PRECEDING}} are derived from FLATLINE_HOURS
-- and POLL_SECONDS (PostgreSQL requires literal ROWS frame bounds).
-- Binding unit required per role (fdd.mask_sweep_val); status/cmd/setpoint roles are not sweep targets.
WITH bind AS (
  SELECT
    MAX(a.unit) FILTER (WHERE a.role = 'oa_t') AS u_oa_t,
    MAX(a.unit) FILTER (WHERE a.role = 'mat') AS u_mat,
    MAX(a.unit) FILTER (WHERE a.role = 'zone_t') AS u_zone_t,
    MAX(a.unit) FILTER (WHERE a.role = 'rat') AS u_rat,
    MAX(a.unit) FILTER (WHERE a.role = 'sat') AS u_sat,
    MAX(a.unit) FILTER (WHERE a.role = 'chw_supply_t') AS u_chw_supply_t,
    MAX(a.unit) FILTER (WHERE a.role = 'chw_return_t') AS u_chw_return_t,
    MAX(a.unit) FILTER (WHERE a.role = 'hw_supply_t') AS u_hw_supply_t,
    MAX(a.unit) FILTER (WHERE a.role = 'hw_return_t') AS u_hw_return_t,
    MAX(a.unit) FILTER (WHERE a.role = 'oa_h') AS u_oa_h,
    MAX(a.unit) FILTER (WHERE a.role = 'ra_h') AS u_ra_h,
    MAX(a.unit) FILTER (WHERE a.role = 'zone_rh') AS u_zone_rh,
    MAX(a.unit) FILTER (WHERE a.role = 'ma_h') AS u_ma_h,
    MAX(a.unit) FILTER (WHERE a.role = 'sa_h') AS u_sa_h
  FROM authorized_series a
  JOIN equipment e ON e.building_id = a.site_id AND e.equipment_id = a.equipment_id
  WHERE e.equipment_id = (SELECT MIN(equipment_id) FROM history)
    AND (SELECT count(*)::int FROM authorized_series c
         WHERE c.site_id = a.site_id AND c.equipment_id = a.equipment_id AND c.role = a.role) = 1
),
gated AS (
  SELECT
    h.equipment_id,
    h.timestamp_utc,
    fdd.mask_sweep_val('oa_t', b.u_oa_t, h.oa_t) AS oa_t,
    fdd.mask_sweep_val('mat', b.u_mat, h.mat) AS mat,
    fdd.mask_sweep_val('zone_t', b.u_zone_t, h.zone_t) AS zone_t,
    fdd.mask_sweep_val('rat', b.u_rat, h.rat) AS rat,
    fdd.mask_sweep_val('sat', b.u_sat, h.sat) AS sat,
    fdd.mask_sweep_val('chw_supply_t', b.u_chw_supply_t, h.chw_supply_t) AS chw_supply_t,
    fdd.mask_sweep_val('chw_return_t', b.u_chw_return_t, h.chw_return_t) AS chw_return_t,
    fdd.mask_sweep_val('hw_supply_t', b.u_hw_supply_t, h.hw_supply_t) AS hw_supply_t,
    fdd.mask_sweep_val('hw_return_t', b.u_hw_return_t, h.hw_return_t) AS hw_return_t,
    fdd.mask_sweep_val('oa_h', b.u_oa_h, h.oa_h) AS oa_h,
    fdd.mask_sweep_val('ra_h', b.u_ra_h, h.ra_h) AS ra_h,
    fdd.mask_sweep_val('zone_rh', b.u_zone_rh, h.zone_rh) AS zone_rh,
    fdd.mask_sweep_val('ma_h', b.u_ma_h, h.ma_h) AS ma_h,
    fdd.mask_sweep_val('sa_h', b.u_sa_h, h.sa_h) AS sa_h,
    h.fan_cmd,
    h.fan_status,
    h.pump_status,
    h.chw_pump_cmd,
    h.chiller_status
  FROM history h
  CROSS JOIN bind b
),
h AS (
  SELECT
    equipment_id,
    timestamp_utc,
    oa_t, mat, zone_t, rat, sat,
    chw_supply_t, chw_return_t, hw_supply_t, hw_return_t,
    oa_h, ra_h, zone_rh, ma_h, sa_h,
    CASE
      WHEN fan_status IS NOT NULL THEN CASE WHEN fan_status > 0.05 THEN 1 ELSE 0 END
      WHEN fan_cmd IS NOT NULL THEN CASE WHEN (CASE WHEN fan_cmd > 1.0 THEN fan_cmd / 100.0 ELSE fan_cmd END) > 0.01 THEN 1 ELSE 0 END
      WHEN pump_status IS NOT NULL THEN CASE WHEN pump_status > 0.05 THEN 1 ELSE 0 END
      WHEN chw_pump_cmd IS NOT NULL THEN CASE WHEN (CASE WHEN chw_pump_cmd > 1.0 THEN chw_pump_cmd / 100.0 ELSE chw_pump_cmd END) > 0.05 THEN 1 ELSE 0 END
      WHEN chiller_status IS NOT NULL THEN CASE WHEN chiller_status > 0.05 THEN 1 ELSE 0 END
      ELSE 1
    END AS energized
  FROM gated
),
win AS (
  SELECT
    equipment_id,
    timestamp_utc,
    energized,
    COUNT(oa_t) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS BETWEEN {{FLATLINE_ROWS_PRECEDING}} PRECEDING AND CURRENT ROW) AS n_oa_t,
    MAX(oa_t) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS BETWEEN {{FLATLINE_ROWS_PRECEDING}} PRECEDING AND CURRENT ROW)
      - MIN(oa_t) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS BETWEEN {{FLATLINE_ROWS_PRECEDING}} PRECEDING AND CURRENT ROW) AS span_oa_t,
    COUNT(mat) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS BETWEEN {{FLATLINE_ROWS_PRECEDING}} PRECEDING AND CURRENT ROW) AS n_mat,
    MAX(mat) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS BETWEEN {{FLATLINE_ROWS_PRECEDING}} PRECEDING AND CURRENT ROW)
      - MIN(mat) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS BETWEEN {{FLATLINE_ROWS_PRECEDING}} PRECEDING AND CURRENT ROW) AS span_mat,
    COUNT(zone_t) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS BETWEEN {{FLATLINE_ROWS_PRECEDING}} PRECEDING AND CURRENT ROW) AS n_zone_t,
    MAX(zone_t) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS BETWEEN {{FLATLINE_ROWS_PRECEDING}} PRECEDING AND CURRENT ROW)
      - MIN(zone_t) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS BETWEEN {{FLATLINE_ROWS_PRECEDING}} PRECEDING AND CURRENT ROW) AS span_zone_t,
    COUNT(rat) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS BETWEEN {{FLATLINE_ROWS_PRECEDING}} PRECEDING AND CURRENT ROW) AS n_rat,
    MAX(rat) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS BETWEEN {{FLATLINE_ROWS_PRECEDING}} PRECEDING AND CURRENT ROW)
      - MIN(rat) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS BETWEEN {{FLATLINE_ROWS_PRECEDING}} PRECEDING AND CURRENT ROW) AS span_rat,
    COUNT(sat) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS BETWEEN {{FLATLINE_ROWS_PRECEDING}} PRECEDING AND CURRENT ROW) AS n_sat,
    MAX(sat) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS BETWEEN {{FLATLINE_ROWS_PRECEDING}} PRECEDING AND CURRENT ROW)
      - MIN(sat) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS BETWEEN {{FLATLINE_ROWS_PRECEDING}} PRECEDING AND CURRENT ROW) AS span_sat,
    COUNT(chw_supply_t) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS BETWEEN {{FLATLINE_ROWS_PRECEDING}} PRECEDING AND CURRENT ROW) AS n_chw_supply_t,
    MAX(chw_supply_t) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS BETWEEN {{FLATLINE_ROWS_PRECEDING}} PRECEDING AND CURRENT ROW)
      - MIN(chw_supply_t) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS BETWEEN {{FLATLINE_ROWS_PRECEDING}} PRECEDING AND CURRENT ROW) AS span_chw_supply_t,
    COUNT(chw_return_t) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS BETWEEN {{FLATLINE_ROWS_PRECEDING}} PRECEDING AND CURRENT ROW) AS n_chw_return_t,
    MAX(chw_return_t) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS BETWEEN {{FLATLINE_ROWS_PRECEDING}} PRECEDING AND CURRENT ROW)
      - MIN(chw_return_t) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS BETWEEN {{FLATLINE_ROWS_PRECEDING}} PRECEDING AND CURRENT ROW) AS span_chw_return_t,
    COUNT(hw_supply_t) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS BETWEEN {{FLATLINE_ROWS_PRECEDING}} PRECEDING AND CURRENT ROW) AS n_hw_supply_t,
    MAX(hw_supply_t) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS BETWEEN {{FLATLINE_ROWS_PRECEDING}} PRECEDING AND CURRENT ROW)
      - MIN(hw_supply_t) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS BETWEEN {{FLATLINE_ROWS_PRECEDING}} PRECEDING AND CURRENT ROW) AS span_hw_supply_t,
    COUNT(hw_return_t) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS BETWEEN {{FLATLINE_ROWS_PRECEDING}} PRECEDING AND CURRENT ROW) AS n_hw_return_t,
    MAX(hw_return_t) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS BETWEEN {{FLATLINE_ROWS_PRECEDING}} PRECEDING AND CURRENT ROW)
      - MIN(hw_return_t) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS BETWEEN {{FLATLINE_ROWS_PRECEDING}} PRECEDING AND CURRENT ROW) AS span_hw_return_t,
    COUNT(oa_h) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS BETWEEN {{FLATLINE_ROWS_PRECEDING}} PRECEDING AND CURRENT ROW) AS n_oa_h,
    MAX(oa_h) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS BETWEEN {{FLATLINE_ROWS_PRECEDING}} PRECEDING AND CURRENT ROW)
      - MIN(oa_h) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS BETWEEN {{FLATLINE_ROWS_PRECEDING}} PRECEDING AND CURRENT ROW) AS span_oa_h,
    COUNT(ra_h) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS BETWEEN {{FLATLINE_ROWS_PRECEDING}} PRECEDING AND CURRENT ROW) AS n_ra_h,
    MAX(ra_h) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS BETWEEN {{FLATLINE_ROWS_PRECEDING}} PRECEDING AND CURRENT ROW)
      - MIN(ra_h) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS BETWEEN {{FLATLINE_ROWS_PRECEDING}} PRECEDING AND CURRENT ROW) AS span_ra_h,
    COUNT(zone_rh) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS BETWEEN {{FLATLINE_ROWS_PRECEDING}} PRECEDING AND CURRENT ROW) AS n_zone_rh,
    MAX(zone_rh) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS BETWEEN {{FLATLINE_ROWS_PRECEDING}} PRECEDING AND CURRENT ROW)
      - MIN(zone_rh) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS BETWEEN {{FLATLINE_ROWS_PRECEDING}} PRECEDING AND CURRENT ROW) AS span_zone_rh,
    COUNT(ma_h) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS BETWEEN {{FLATLINE_ROWS_PRECEDING}} PRECEDING AND CURRENT ROW) AS n_ma_h,
    MAX(ma_h) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS BETWEEN {{FLATLINE_ROWS_PRECEDING}} PRECEDING AND CURRENT ROW)
      - MIN(ma_h) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS BETWEEN {{FLATLINE_ROWS_PRECEDING}} PRECEDING AND CURRENT ROW) AS span_ma_h,
    COUNT(sa_h) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS BETWEEN {{FLATLINE_ROWS_PRECEDING}} PRECEDING AND CURRENT ROW) AS n_sa_h,
    MAX(sa_h) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS BETWEEN {{FLATLINE_ROWS_PRECEDING}} PRECEDING AND CURRENT ROW)
      - MIN(sa_h) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS BETWEEN {{FLATLINE_ROWS_PRECEDING}} PRECEDING AND CURRENT ROW) AS span_sa_h
  FROM h
),
base AS (
  SELECT
    equipment_id,
    timestamp_utc,
    CAST(CASE
      WHEN COALESCE(energized, 0) = 0 THEN 0
      WHEN n_oa_t >= {{FLATLINE_ROWS}} AND span_oa_t <= {{FLATLINE_TOL}} THEN 1
      WHEN n_mat >= {{FLATLINE_ROWS}} AND span_mat <= {{FLATLINE_TOL}} THEN 1
      WHEN n_zone_t >= {{FLATLINE_ROWS}} AND span_zone_t <= {{FLATLINE_TOL}} THEN 1
      WHEN n_rat >= {{FLATLINE_ROWS}} AND span_rat <= {{FLATLINE_TOL}} THEN 1
      WHEN n_sat >= {{FLATLINE_ROWS}} AND span_sat <= {{FLATLINE_TOL}} THEN 1
      WHEN n_chw_supply_t >= {{FLATLINE_ROWS}} AND span_chw_supply_t <= {{FLATLINE_TOL}} THEN 1
      WHEN n_chw_return_t >= {{FLATLINE_ROWS}} AND span_chw_return_t <= {{FLATLINE_TOL}} THEN 1
      WHEN n_hw_supply_t >= {{FLATLINE_ROWS}} AND span_hw_supply_t <= {{FLATLINE_TOL}} THEN 1
      WHEN n_hw_return_t >= {{FLATLINE_ROWS}} AND span_hw_return_t <= {{FLATLINE_TOL}} THEN 1
      WHEN n_oa_h >= {{FLATLINE_ROWS}} AND span_oa_h <= {{FLATLINE_TOL}} THEN 1
      WHEN n_ra_h >= {{FLATLINE_ROWS}} AND span_ra_h <= {{FLATLINE_TOL}} THEN 1
      WHEN n_zone_rh >= {{FLATLINE_ROWS}} AND span_zone_rh <= {{FLATLINE_TOL}} THEN 1
      WHEN n_ma_h >= {{FLATLINE_ROWS}} AND span_ma_h <= {{FLATLINE_TOL}} THEN 1
      WHEN n_sa_h >= {{FLATLINE_ROWS}} AND span_sa_h <= {{FLATLINE_TOL}} THEN 1
      ELSE 0
    END AS INT) AS raw_fault
  FROM win
),
elapsed_hold AS (
  -- Forward sample-and-hold. A gap longer than MAX_GAP_HOURS is unknown:
  -- it is not fault time, not covered time, and it breaks confirmation.
  -- The last sample has no forward interval.
  SELECT
    stepped.*,
    CASE
      WHEN stepped.dt_seconds IS NULL
        OR stepped.dt_seconds <= 0.0
        OR stepped.dt_seconds > ({{MAX_GAP_HOURS}} * 3600.0)
      THEN 0.0
      ELSE stepped.dt_seconds
    END AS held_seconds,
    CASE
      WHEN stepped.dt_seconds > ({{MAX_GAP_HOURS}} * 3600.0) THEN 1
      ELSE 0
    END AS gap_after
  FROM (
    SELECT
      src.*,
      EXTRACT(EPOCH FROM (
        LEAD(src.timestamp_utc) OVER (
          PARTITION BY src.equipment_id ORDER BY src.timestamp_utc
        ) - src.timestamp_utc
      )) AS dt_seconds
    FROM base src
  ) stepped
),
lagged AS (
  SELECT
    *,
    CASE
      WHEN raw_fault = LAG(raw_fault) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc)
       AND COALESCE(LAG(gap_after) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc), 0) = 0
      THEN 0 ELSE 1
    END AS is_new_streak
  FROM elapsed_hold
),
grp AS (
  SELECT
    *,
    SUM(is_new_streak)
      OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS UNBOUNDED PRECEDING) AS streak_id
  FROM lagged
),
ranked AS (
  SELECT
    *,
    SUM(held_seconds) OVER (
      PARTITION BY equipment_id, streak_id ORDER BY timestamp_utc
      ROWS UNBOUNDED PRECEDING
    ) AS streak_elapsed
  FROM grp
),
final AS (
  SELECT
    equipment_id,
    held_seconds,
    CASE WHEN raw_fault = 1 AND streak_elapsed >= {{CONFIRM_SECONDS}} THEN 1 ELSE 0 END AS confirmed
  FROM ranked
)
SELECT
  equipment_id,
  SUM(CASE WHEN confirmed = 1 THEN held_seconds ELSE 0.0 END) / 3600.0 AS fault_hours,
  SUM(held_seconds) / 3600.0 AS covered_hours,
  100.0 * SUM(CASE WHEN confirmed = 1 THEN held_seconds ELSE 0.0 END) / NULLIF(SUM(held_seconds), 0.0) AS fault_pct
FROM final
GROUP BY equipment_id;
```
{% endraw %}

### sv_range.sql

`sql/fdd/postgres/rules/sv_range.sql`

{% raw %}
```sql
-- PostgreSQL adaptation. Render numeric template parameters with render_rule.py.
-- Inputs must be scoped to one tenant/site and cadence; see README.md.
-- sv_range.sql — Sensor out of hard range (pandas SENSOR_LIMITS catalog)
-- Do not force everything through oa_t. Humidity/pressure are not temperature-scaled.
-- Points without a declared binding unit are masked (not assessed), matching pandas sweep_assessable_role.
WITH bind AS (
  SELECT
    MAX(a.unit) FILTER (WHERE a.role = 'oa_t') AS u_oa_t,
    MAX(a.unit) FILTER (WHERE a.role = 'mat') AS u_mat,
    MAX(a.unit) FILTER (WHERE a.role = 'zone_t') AS u_zone_t,
    MAX(a.unit) FILTER (WHERE a.role = 'rat') AS u_rat,
    MAX(a.unit) FILTER (WHERE a.role = 'sat') AS u_sat,
    MAX(a.unit) FILTER (WHERE a.role = 'chw_supply_t') AS u_chw_supply_t,
    MAX(a.unit) FILTER (WHERE a.role = 'chw_return_t') AS u_chw_return_t,
    MAX(a.unit) FILTER (WHERE a.role = 'hw_supply_t') AS u_hw_supply_t,
    MAX(a.unit) FILTER (WHERE a.role = 'hw_return_t') AS u_hw_return_t,
    MAX(a.unit) FILTER (WHERE a.role = 'oa_h') AS u_oa_h,
    MAX(a.unit) FILTER (WHERE a.role = 'ra_h') AS u_ra_h,
    MAX(a.unit) FILTER (WHERE a.role = 'zone_rh') AS u_zone_rh,
    MAX(a.unit) FILTER (WHERE a.role = 'ma_h') AS u_ma_h,
    MAX(a.unit) FILTER (WHERE a.role = 'sa_h') AS u_sa_h,
    MAX(a.unit) FILTER (WHERE a.role = 'duct_static') AS u_duct_static
  FROM authorized_series a
  JOIN equipment e ON e.building_id = a.site_id AND e.equipment_id = a.equipment_id
  WHERE e.equipment_id = (SELECT MIN(equipment_id) FROM history)
    AND (SELECT count(*)::int FROM authorized_series c
         WHERE c.site_id = a.site_id AND c.equipment_id = a.equipment_id AND c.role = a.role) = 1
),
gated AS (
  SELECT
    h.equipment_id,
    h.timestamp_utc,
    fdd.mask_sweep_val('oa_t', b.u_oa_t, h.oa_t) AS oa_t,
    fdd.mask_sweep_val('mat', b.u_mat, h.mat) AS mat,
    fdd.mask_sweep_val('zone_t', b.u_zone_t, h.zone_t) AS zone_t,
    fdd.mask_sweep_val('rat', b.u_rat, h.rat) AS rat,
    fdd.mask_sweep_val('sat', b.u_sat, h.sat) AS sat,
    fdd.mask_sweep_val('chw_supply_t', b.u_chw_supply_t, h.chw_supply_t) AS chw_supply_t,
    fdd.mask_sweep_val('chw_return_t', b.u_chw_return_t, h.chw_return_t) AS chw_return_t,
    fdd.mask_sweep_val('hw_supply_t', b.u_hw_supply_t, h.hw_supply_t) AS hw_supply_t,
    fdd.mask_sweep_val('hw_return_t', b.u_hw_return_t, h.hw_return_t) AS hw_return_t,
    fdd.mask_sweep_val('oa_h', b.u_oa_h, h.oa_h) AS oa_h,
    fdd.mask_sweep_val('ra_h', b.u_ra_h, h.ra_h) AS ra_h,
    fdd.mask_sweep_val('zone_rh', b.u_zone_rh, h.zone_rh) AS zone_rh,
    fdd.mask_sweep_val('ma_h', b.u_ma_h, h.ma_h) AS ma_h,
    fdd.mask_sweep_val('sa_h', b.u_sa_h, h.sa_h) AS sa_h,
    fdd.mask_sweep_val('duct_static', b.u_duct_static, h.duct_static) AS duct_static,
    h.fan_cmd,
    h.fan_status,
    h.pump_status,
    h.chw_pump_cmd,
    h.chiller_status
  FROM history h
  CROSS JOIN bind b
),
h AS (
  SELECT
    equipment_id,
    timestamp_utc,
    oa_t, mat, zone_t, rat, sat,
    chw_supply_t, chw_return_t, hw_supply_t, hw_return_t,
    oa_h, ra_h, zone_rh, ma_h, sa_h, duct_static,
    fan_cmd, fan_status, pump_status, chw_pump_cmd, chiller_status,
    CASE
      WHEN fan_status IS NOT NULL THEN CASE WHEN fan_status > 0.05 THEN 1 ELSE 0 END
      WHEN fan_cmd IS NOT NULL THEN CASE WHEN (CASE WHEN fan_cmd > 1.0 THEN fan_cmd / 100.0 ELSE fan_cmd END) > 0.01 THEN 1 ELSE 0 END
      WHEN pump_status IS NOT NULL THEN CASE WHEN pump_status > 0.05 THEN 1 ELSE 0 END
      WHEN chw_pump_cmd IS NOT NULL THEN CASE WHEN (CASE WHEN chw_pump_cmd > 1.0 THEN chw_pump_cmd / 100.0 ELSE chw_pump_cmd END) > 0.05 THEN 1 ELSE 0 END
      WHEN chiller_status IS NOT NULL THEN CASE WHEN chiller_status > 0.05 THEN 1 ELSE 0 END
      ELSE 1
    END AS energized
  FROM gated
),
base AS (
  SELECT
    equipment_id,
    timestamp_utc,
    CAST(CASE
      WHEN COALESCE(energized, 0) = 0 THEN 0
      WHEN oa_t IS NOT NULL AND (oa_t = CAST('NaN' AS DOUBLE PRECISION) OR oa_t < -51.111111 * {{RANGE_SCALE_TEMPERATURE}} OR oa_t > 54.444444 * {{RANGE_SCALE_TEMPERATURE}}) THEN 1
      WHEN mat IS NOT NULL AND (mat = CAST('NaN' AS DOUBLE PRECISION) OR mat < -28.888889 * {{RANGE_SCALE_TEMPERATURE}} OR mat > 43.333333 * {{RANGE_SCALE_TEMPERATURE}}) THEN 1
      WHEN zone_t IS NOT NULL AND (zone_t = CAST('NaN' AS DOUBLE PRECISION) OR zone_t < 4.444444 * {{RANGE_SCALE_TEMPERATURE}} OR zone_t > 37.777778 * {{RANGE_SCALE_TEMPERATURE}}) THEN 1
      WHEN rat IS NOT NULL AND (rat = CAST('NaN' AS DOUBLE PRECISION) OR rat < 4.444444 * {{RANGE_SCALE_TEMPERATURE}} OR rat > 37.777778 * {{RANGE_SCALE_TEMPERATURE}}) THEN 1
      WHEN sat IS NOT NULL AND (sat = CAST('NaN' AS DOUBLE PRECISION) OR sat < -1.111111 * {{RANGE_SCALE_TEMPERATURE}} OR sat > 65.555556 * {{RANGE_SCALE_TEMPERATURE}}) THEN 1
      WHEN chw_supply_t IS NOT NULL AND (chw_supply_t = CAST('NaN' AS DOUBLE PRECISION) OR chw_supply_t < -1.111111 * {{RANGE_SCALE_TEMPERATURE}} OR chw_supply_t > 26.666667 * {{RANGE_SCALE_TEMPERATURE}}) THEN 1
      WHEN chw_return_t IS NOT NULL AND (chw_return_t = CAST('NaN' AS DOUBLE PRECISION) OR chw_return_t < -1.111111 * {{RANGE_SCALE_TEMPERATURE}} OR chw_return_t > 32.222222 * {{RANGE_SCALE_TEMPERATURE}}) THEN 1
      WHEN hw_supply_t IS NOT NULL AND (hw_supply_t = CAST('NaN' AS DOUBLE PRECISION) OR hw_supply_t < 4.444444 * {{RANGE_SCALE_TEMPERATURE}} OR hw_supply_t > 104.444444 * {{RANGE_SCALE_TEMPERATURE}}) THEN 1
      WHEN hw_return_t IS NOT NULL AND (hw_return_t = CAST('NaN' AS DOUBLE PRECISION) OR hw_return_t < 4.444444 * {{RANGE_SCALE_TEMPERATURE}} OR hw_return_t > 104.444444 * {{RANGE_SCALE_TEMPERATURE}}) THEN 1
      WHEN oa_h IS NOT NULL AND (oa_h = CAST('NaN' AS DOUBLE PRECISION) OR oa_h < 0.0 * {{RANGE_SCALE_HUMIDITY}} OR oa_h > 100.0 * {{RANGE_SCALE_HUMIDITY}}) THEN 1
      WHEN ra_h IS NOT NULL AND (ra_h = CAST('NaN' AS DOUBLE PRECISION) OR ra_h < 0.0 * {{RANGE_SCALE_HUMIDITY}} OR ra_h > 100.0 * {{RANGE_SCALE_HUMIDITY}}) THEN 1
      WHEN zone_rh IS NOT NULL AND (zone_rh = CAST('NaN' AS DOUBLE PRECISION) OR zone_rh < 0.0 * {{RANGE_SCALE_HUMIDITY}} OR zone_rh > 100.0 * {{RANGE_SCALE_HUMIDITY}}) THEN 1
      WHEN ma_h IS NOT NULL AND (ma_h = CAST('NaN' AS DOUBLE PRECISION) OR ma_h < 0.0 * {{RANGE_SCALE_HUMIDITY}} OR ma_h > 100.0 * {{RANGE_SCALE_HUMIDITY}}) THEN 1
      WHEN sa_h IS NOT NULL AND (sa_h = CAST('NaN' AS DOUBLE PRECISION) OR sa_h < 0.0 * {{RANGE_SCALE_HUMIDITY}} OR sa_h > 100.0 * {{RANGE_SCALE_HUMIDITY}}) THEN 1
      WHEN duct_static IS NOT NULL AND (duct_static = CAST('NaN' AS DOUBLE PRECISION) OR duct_static < -248.84 * {{RANGE_SCALE_PRESSURE}} OR duct_static > 1990.72 * {{RANGE_SCALE_PRESSURE}}) THEN 1
      ELSE 0
    END AS INT) AS raw_fault
  FROM h
),
elapsed_hold AS (
  -- Forward sample-and-hold. A gap longer than MAX_GAP_HOURS is unknown:
  -- it is not fault time, not covered time, and it breaks confirmation.
  -- The last sample has no forward interval.
  SELECT
    stepped.*,
    CASE
      WHEN stepped.dt_seconds IS NULL
        OR stepped.dt_seconds <= 0.0
        OR stepped.dt_seconds > ({{MAX_GAP_HOURS}} * 3600.0)
      THEN 0.0
      ELSE stepped.dt_seconds
    END AS held_seconds,
    CASE
      WHEN stepped.dt_seconds > ({{MAX_GAP_HOURS}} * 3600.0) THEN 1
      ELSE 0
    END AS gap_after
  FROM (
    SELECT
      src.*,
      EXTRACT(EPOCH FROM (
        LEAD(src.timestamp_utc) OVER (
          PARTITION BY src.equipment_id ORDER BY src.timestamp_utc
        ) - src.timestamp_utc
      )) AS dt_seconds
    FROM base src
  ) stepped
),
lagged AS (
  SELECT
    *,
    CASE
      WHEN raw_fault = LAG(raw_fault) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc)
       AND COALESCE(LAG(gap_after) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc), 0) = 0
      THEN 0 ELSE 1
    END AS is_new_streak
  FROM elapsed_hold
),
grp AS (
  SELECT
    *,
    SUM(is_new_streak)
      OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS UNBOUNDED PRECEDING) AS streak_id
  FROM lagged
),
ranked AS (
  SELECT
    *,
    SUM(held_seconds) OVER (
      PARTITION BY equipment_id, streak_id ORDER BY timestamp_utc
      ROWS UNBOUNDED PRECEDING
    ) AS streak_elapsed
  FROM grp
),
final AS (
  SELECT
    equipment_id,
    held_seconds,
    CASE WHEN raw_fault = 1 AND streak_elapsed >= {{CONFIRM_SECONDS}} THEN 1 ELSE 0 END AS confirmed
  FROM ranked
)
SELECT
  equipment_id,
  SUM(CASE WHEN confirmed = 1 THEN held_seconds ELSE 0.0 END) / 3600.0 AS fault_hours,
  SUM(held_seconds) / 3600.0 AS covered_hours,
  100.0 * SUM(CASE WHEN confirmed = 1 THEN held_seconds ELSE 0.0 END) / NULLIF(SUM(held_seconds), 0.0) AS fault_pct
FROM final
GROUP BY equipment_id;
```
{% endraw %}

### sv_rate.sql

`sql/fdd/postgres/rules/sv_rate.sql`

{% raw %}
```sql
-- PostgreSQL adaptation. Render numeric template parameters with render_rule.py.
-- Inputs must be scoped to one tenant/site and cadence; see README.md.
-- sv_rate.sql — Context-aware sensor rate of change (portable channels)
-- Rate is normalized to °C/h so the threshold is poll-interval independent, and
-- the exceedance must be *sustained* (two consecutive samples) to separate a
-- slew from a one-sample SV-SPIKE. Samples separated by more than
-- PERSISTENCE_MIN are treated as a data gap, not a slew.
WITH h AS (
  SELECT
    equipment_id,
    timestamp_utc,
    oa_t, mat, zone_t, rat, sat,
    LAG(oa_t) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc) AS prev_oa_t,
    LAG(mat) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc) AS prev_mat,
    LAG(zone_t) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc) AS prev_zone_t,
    LAG(rat) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc) AS prev_rat,
    LAG(sat) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc) AS prev_sat,
    LAG(timestamp_utc) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc) AS prev_ts
  FROM history
),
rates AS (
  SELECT
    equipment_id,
    timestamp_utc,
    CAST(EXTRACT(EPOCH FROM (timestamp_utc - prev_ts)) AS DOUBLE PRECISION) / 3600.0 AS dt_hours,
    oa_t - prev_oa_t AS d_oa_t,
    mat - prev_mat AS d_mat,
    zone_t - prev_zone_t AS d_zone_t,
    rat - prev_rat AS d_rat,
    sat - prev_sat AS d_sat,
    prev_ts
  FROM h
),
flagged AS (
  SELECT
    equipment_id,
    timestamp_utc,
    CAST(CASE
      WHEN prev_ts IS NULL THEN 0
      WHEN CAST(EXTRACT(EPOCH FROM (timestamp_utc - prev_ts)) AS DOUBLE PRECISION) > {{MAX_GAP_HOURS}} * 3600.0 THEN 0
      WHEN dt_hours IS NULL OR dt_hours <= 0.0 THEN 0
      WHEN ABS(d_oa_t) / dt_hours > ({{STEADY_FAULT_PER_HOUR}} * {{SENSOR_SPAN}} / 100.0) THEN 1
      WHEN ABS(d_mat) / dt_hours > ({{STEADY_FAULT_PER_HOUR}} * {{SENSOR_SPAN}} / 100.0) THEN 1
      WHEN ABS(d_zone_t) / dt_hours > ({{STEADY_FAULT_PER_HOUR}} * {{SENSOR_SPAN}} / 100.0) THEN 1
      WHEN ABS(d_rat) / dt_hours > ({{STEADY_FAULT_PER_HOUR}} * {{SENSOR_SPAN}} / 100.0) THEN 1
      WHEN ABS(d_sat) / dt_hours > ({{STEADY_FAULT_PER_HOUR}} * {{SENSOR_SPAN}} / 100.0) THEN 1
      ELSE 0
    END AS INT) AS over_rate
  FROM rates
),
base AS (
  SELECT
    equipment_id,
    timestamp_utc,
    CAST(CASE
      WHEN over_rate = 1
       AND COALESCE(LAG(over_rate) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc), 0) = 1
      THEN 1 ELSE 0
    END AS INT) AS raw_fault
  FROM flagged
),
elapsed_hold AS (
  -- Forward sample-and-hold. A gap longer than MAX_GAP_HOURS is unknown:
  -- it is not fault time, not covered time, and it breaks confirmation.
  -- The last sample has no forward interval.
  SELECT
    stepped.*,
    CASE
      WHEN stepped.dt_seconds IS NULL
        OR stepped.dt_seconds <= 0.0
        OR stepped.dt_seconds > ({{MAX_GAP_HOURS}} * 3600.0)
      THEN 0.0
      ELSE stepped.dt_seconds
    END AS held_seconds,
    CASE
      WHEN stepped.dt_seconds > ({{MAX_GAP_HOURS}} * 3600.0) THEN 1
      ELSE 0
    END AS gap_after
  FROM (
    SELECT
      src.*,
      EXTRACT(EPOCH FROM (
        LEAD(src.timestamp_utc) OVER (
          PARTITION BY src.equipment_id ORDER BY src.timestamp_utc
        ) - src.timestamp_utc
      )) AS dt_seconds
    FROM base src
  ) stepped
),
lagged AS (
  SELECT
    *,
    CASE
      WHEN raw_fault = LAG(raw_fault) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc)
       AND COALESCE(LAG(gap_after) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc), 0) = 0
      THEN 0 ELSE 1
    END AS is_new_streak
  FROM elapsed_hold
),
grp AS (
  SELECT
    *,
    SUM(is_new_streak)
      OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS UNBOUNDED PRECEDING) AS streak_id
  FROM lagged
),
ranked AS (
  SELECT
    *,
    SUM(held_seconds) OVER (
      PARTITION BY equipment_id, streak_id ORDER BY timestamp_utc
      ROWS UNBOUNDED PRECEDING
    ) AS streak_elapsed
  FROM grp
),
final AS (
  SELECT
    equipment_id,
    held_seconds,
    CASE WHEN raw_fault = 1 AND streak_elapsed >= {{CONFIRM_SECONDS}} THEN 1 ELSE 0 END AS confirmed
  FROM ranked
)
SELECT
  equipment_id,
  SUM(CASE WHEN confirmed = 1 THEN held_seconds ELSE 0.0 END) / 3600.0 AS fault_hours,
  SUM(held_seconds) / 3600.0 AS covered_hours,
  100.0 * SUM(CASE WHEN confirmed = 1 THEN held_seconds ELSE 0.0 END) / NULLIF(SUM(held_seconds), 0.0) AS fault_pct
FROM final
GROUP BY equipment_id;
```
{% endraw %}

### sv_spike.sql

`sql/fdd/postgres/rules/sv_spike.sql`

{% raw %}
```sql
-- PostgreSQL adaptation. Render numeric template parameters with render_rule.py.
-- Inputs must be scoped to one tenant/site and cadence; see README.md.
-- sv_spike.sql — Sensor rate-of-change spike — pandas SENSOR_LIMITS catalog
-- Per-role spike limits (scaled by SPIKE_SCALE). Humidity/pressure included.
WITH h AS (
  SELECT
    equipment_id,
    timestamp_utc,
    oa_t, mat, zone_t, rat, sat,
    chw_supply_t, chw_return_t, hw_supply_t, hw_return_t, oa_h, duct_static,
    LAG(oa_t) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc) AS prev_oa_t,
    LAG(mat) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc) AS prev_mat,
    LAG(zone_t) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc) AS prev_zone_t,
    LAG(rat) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc) AS prev_rat,
    LAG(sat) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc) AS prev_sat,
    LAG(chw_supply_t) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc) AS prev_chw_supply_t,
    LAG(chw_return_t) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc) AS prev_chw_return_t,
    LAG(hw_supply_t) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc) AS prev_hw_supply_t,
    LAG(hw_return_t) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc) AS prev_hw_return_t,
    LAG(oa_h) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc) AS prev_oa_h,
    LAG(duct_static) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc) AS prev_duct_static,
    fan_cmd, fan_status, pump_status, chw_pump_cmd, chiller_status,
    CASE
      WHEN fan_status IS NOT NULL THEN CASE WHEN fan_status > 0.05 THEN 1 ELSE 0 END
      WHEN fan_cmd IS NOT NULL THEN CASE WHEN (CASE WHEN fan_cmd > 1.0 THEN fan_cmd / 100.0 ELSE fan_cmd END) > 0.01 THEN 1 ELSE 0 END
      WHEN pump_status IS NOT NULL THEN CASE WHEN pump_status > 0.05 THEN 1 ELSE 0 END
      WHEN chw_pump_cmd IS NOT NULL THEN CASE WHEN (CASE WHEN chw_pump_cmd > 1.0 THEN chw_pump_cmd / 100.0 ELSE chw_pump_cmd END) > 0.05 THEN 1 ELSE 0 END
      WHEN chiller_status IS NOT NULL THEN CASE WHEN chiller_status > 0.05 THEN 1 ELSE 0 END
      ELSE 1
    END AS energized
  FROM history
),
base AS (
  SELECT
    equipment_id,
    timestamp_utc,
    CAST(CASE
      WHEN {{REQUIRE_OPERATIONAL_GATE}} >= 0.5 AND COALESCE(energized, 0) = 0 THEN 0
      WHEN oa_t IS NOT NULL AND prev_oa_t IS NOT NULL AND ABS(oa_t - prev_oa_t) > 36.0 * {{SPIKE_SCALE_TEMPERATURE}} THEN 1
      WHEN mat IS NOT NULL AND prev_mat IS NOT NULL AND ABS(mat - prev_mat) > 25.0 * {{SPIKE_SCALE_TEMPERATURE}} THEN 1
      WHEN zone_t IS NOT NULL AND prev_zone_t IS NOT NULL AND ABS(zone_t - prev_zone_t) > 12.0 * {{SPIKE_SCALE_TEMPERATURE}} THEN 1
      WHEN rat IS NOT NULL AND prev_rat IS NOT NULL AND ABS(rat - prev_rat) > 12.0 * {{SPIKE_SCALE_TEMPERATURE}} THEN 1
      WHEN sat IS NOT NULL AND prev_sat IS NOT NULL AND ABS(sat - prev_sat) > 40.0 * {{SPIKE_SCALE_TEMPERATURE}} THEN 1
      WHEN chw_supply_t IS NOT NULL AND prev_chw_supply_t IS NOT NULL AND ABS(chw_supply_t - prev_chw_supply_t) > 20.0 * {{SPIKE_SCALE_TEMPERATURE}} THEN 1
      WHEN chw_return_t IS NOT NULL AND prev_chw_return_t IS NOT NULL AND ABS(chw_return_t - prev_chw_return_t) > 20.0 * {{SPIKE_SCALE_TEMPERATURE}} THEN 1
      WHEN hw_supply_t IS NOT NULL AND prev_hw_supply_t IS NOT NULL AND ABS(hw_supply_t - prev_hw_supply_t) > 60.0 * {{SPIKE_SCALE_TEMPERATURE}} THEN 1
      WHEN hw_return_t IS NOT NULL AND prev_hw_return_t IS NOT NULL AND ABS(hw_return_t - prev_hw_return_t) > 60.0 * {{SPIKE_SCALE_TEMPERATURE}} THEN 1
      WHEN oa_h IS NOT NULL AND prev_oa_h IS NOT NULL AND ABS(oa_h - prev_oa_h) > 25.0 * {{SPIKE_SCALE_HUMIDITY}} THEN 1
      WHEN duct_static IS NOT NULL AND prev_duct_static IS NOT NULL AND ABS(duct_static - prev_duct_static) > 2.0 * {{SPIKE_SCALE_PRESSURE}} THEN 1
      ELSE 0
    END AS INT) AS raw_fault
  FROM h
),
elapsed_hold AS (
  -- Forward sample-and-hold. A gap longer than MAX_GAP_HOURS is unknown:
  -- it is not fault time, not covered time, and it breaks confirmation.
  -- The last sample has no forward interval.
  SELECT
    stepped.*,
    CASE
      WHEN stepped.dt_seconds IS NULL
        OR stepped.dt_seconds <= 0.0
        OR stepped.dt_seconds > ({{MAX_GAP_HOURS}} * 3600.0)
      THEN 0.0
      ELSE stepped.dt_seconds
    END AS held_seconds,
    CASE
      WHEN stepped.dt_seconds > ({{MAX_GAP_HOURS}} * 3600.0) THEN 1
      ELSE 0
    END AS gap_after
  FROM (
    SELECT
      src.*,
      EXTRACT(EPOCH FROM (
        LEAD(src.timestamp_utc) OVER (
          PARTITION BY src.equipment_id ORDER BY src.timestamp_utc
        ) - src.timestamp_utc
      )) AS dt_seconds
    FROM base src
  ) stepped
),
lagged AS (
  SELECT
    *,
    CASE
      WHEN raw_fault = LAG(raw_fault) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc)
       AND COALESCE(LAG(gap_after) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc), 0) = 0
      THEN 0 ELSE 1
    END AS is_new_streak
  FROM elapsed_hold
),
grp AS (
  SELECT
    *,
    SUM(is_new_streak)
      OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS UNBOUNDED PRECEDING) AS streak_id
  FROM lagged
),
ranked AS (
  SELECT
    *,
    SUM(held_seconds) OVER (
      PARTITION BY equipment_id, streak_id ORDER BY timestamp_utc
      ROWS UNBOUNDED PRECEDING
    ) AS streak_elapsed
  FROM grp
),
final AS (
  SELECT
    equipment_id,
    held_seconds,
    CASE WHEN raw_fault = 1 AND streak_elapsed >= {{CONFIRM_SECONDS}} THEN 1 ELSE 0 END AS confirmed
  FROM ranked
)
, cov AS (
  SELECT equipment_id,
    100.0 * AVG(CAST(COALESCE(energized, 1) AS DOUBLE PRECISION)) AS cov_pct
  FROM h
  GROUP BY equipment_id
)
SELECT
  f.equipment_id,
  CASE
    WHEN {{REQUIRE_OPERATIONAL_GATE}} < 0.5 THEN SUM(CASE WHEN f.confirmed = 1 THEN f.held_seconds ELSE 0.0 END) / 3600.0
    WHEN MAX(c.cov_pct) < {{MINIMUM_ACTIVE_COVERAGE_PCT}} THEN 0.0
    ELSE SUM(CASE WHEN f.confirmed = 1 THEN f.held_seconds ELSE 0.0 END) / 3600.0
  END AS fault_hours,
  SUM(f.held_seconds) / 3600.0 AS covered_hours,
  CASE
    WHEN {{REQUIRE_OPERATIONAL_GATE}} < 0.5 THEN 100.0 * SUM(CASE WHEN f.confirmed = 1 THEN f.held_seconds ELSE 0.0 END) / NULLIF(SUM(f.held_seconds), 0.0)
    WHEN MAX(c.cov_pct) < {{MINIMUM_ACTIVE_COVERAGE_PCT}} THEN 0.0
    ELSE 100.0 * SUM(CASE WHEN f.confirmed = 1 THEN f.held_seconds ELSE 0.0 END) / NULLIF(SUM(f.held_seconds), 0.0)
  END AS fault_pct
FROM final f
LEFT JOIN cov c ON f.equipment_id = c.equipment_id
GROUP BY f.equipment_id;
```
{% endraw %}

### sv_stale.sql

`sql/fdd/postgres/rules/sv_stale.sql`

{% raw %}
```sql
-- PostgreSQL adaptation. Render numeric template parameters with render_rule.py.
-- Inputs must be scoped to one tenant/site and cadence; see README.md.
-- sv_stale.sql — Stale data (no fresh samples)
-- Pandas gate is `always` — do not filter fan_cmd (off-period stale still counts).
-- Pandas `_sweep_stale` ANDs FLATLINE_SENSOR_ROLES (SENSOR_LIMITS minus duct static).
-- SQL windows that catalog: five air temps plus chw/hw temps and oa_h.
-- Every mapped analog must sit inside STALE_TOL across the trailing STALE_HOURS
-- window: one live sensor is enough to prove the feed is still updating.
-- {{STALE_ROWS}} / {{STALE_ROWS_PRECEDING}} are derived from STALE_HOURS and
-- POLL_SECONDS (PostgreSQL requires literal ROWS frame bounds).
-- Binding unit required per role (fdd.mask_sweep_val); duct static is not in the stale AND set.
WITH bind AS (
  SELECT
    MAX(a.unit) FILTER (WHERE a.role = 'oa_t') AS u_oa_t,
    MAX(a.unit) FILTER (WHERE a.role = 'mat') AS u_mat,
    MAX(a.unit) FILTER (WHERE a.role = 'zone_t') AS u_zone_t,
    MAX(a.unit) FILTER (WHERE a.role = 'rat') AS u_rat,
    MAX(a.unit) FILTER (WHERE a.role = 'sat') AS u_sat,
    MAX(a.unit) FILTER (WHERE a.role = 'chw_supply_t') AS u_chw_supply_t,
    MAX(a.unit) FILTER (WHERE a.role = 'chw_return_t') AS u_chw_return_t,
    MAX(a.unit) FILTER (WHERE a.role = 'hw_supply_t') AS u_hw_supply_t,
    MAX(a.unit) FILTER (WHERE a.role = 'hw_return_t') AS u_hw_return_t,
    MAX(a.unit) FILTER (WHERE a.role = 'oa_h') AS u_oa_h,
    MAX(a.unit) FILTER (WHERE a.role = 'ra_h') AS u_ra_h,
    MAX(a.unit) FILTER (WHERE a.role = 'zone_rh') AS u_zone_rh,
    MAX(a.unit) FILTER (WHERE a.role = 'ma_h') AS u_ma_h,
    MAX(a.unit) FILTER (WHERE a.role = 'sa_h') AS u_sa_h
  FROM authorized_series a
  JOIN equipment e ON e.building_id = a.site_id AND e.equipment_id = a.equipment_id
  WHERE e.equipment_id = (SELECT MIN(equipment_id) FROM history)
    AND (SELECT count(*)::int FROM authorized_series c
         WHERE c.site_id = a.site_id AND c.equipment_id = a.equipment_id AND c.role = a.role) = 1
),
gated AS (
  SELECT
    h.equipment_id,
    h.timestamp_utc,
    fdd.mask_sweep_val('oa_t', b.u_oa_t, h.oa_t) AS oa_t,
    fdd.mask_sweep_val('mat', b.u_mat, h.mat) AS mat,
    fdd.mask_sweep_val('zone_t', b.u_zone_t, h.zone_t) AS zone_t,
    fdd.mask_sweep_val('rat', b.u_rat, h.rat) AS rat,
    fdd.mask_sweep_val('sat', b.u_sat, h.sat) AS sat,
    fdd.mask_sweep_val('chw_supply_t', b.u_chw_supply_t, h.chw_supply_t) AS chw_supply_t,
    fdd.mask_sweep_val('chw_return_t', b.u_chw_return_t, h.chw_return_t) AS chw_return_t,
    fdd.mask_sweep_val('hw_supply_t', b.u_hw_supply_t, h.hw_supply_t) AS hw_supply_t,
    fdd.mask_sweep_val('hw_return_t', b.u_hw_return_t, h.hw_return_t) AS hw_return_t,
    fdd.mask_sweep_val('oa_h', b.u_oa_h, h.oa_h) AS oa_h,
    fdd.mask_sweep_val('ra_h', b.u_ra_h, h.ra_h) AS ra_h,
    fdd.mask_sweep_val('zone_rh', b.u_zone_rh, h.zone_rh) AS zone_rh,
    fdd.mask_sweep_val('ma_h', b.u_ma_h, h.ma_h) AS ma_h,
    fdd.mask_sweep_val('sa_h', b.u_sa_h, h.sa_h) AS sa_h
  FROM history h
  CROSS JOIN bind b
),
win AS (
  SELECT
    equipment_id,
    timestamp_utc,
    COUNT(oa_t) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS BETWEEN {{STALE_ROWS_PRECEDING}} PRECEDING AND CURRENT ROW) AS n_oa_t,
    MAX(oa_t) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS BETWEEN {{STALE_ROWS_PRECEDING}} PRECEDING AND CURRENT ROW)
      - MIN(oa_t) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS BETWEEN {{STALE_ROWS_PRECEDING}} PRECEDING AND CURRENT ROW) AS span_oa_t,
    COUNT(mat) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS BETWEEN {{STALE_ROWS_PRECEDING}} PRECEDING AND CURRENT ROW) AS n_mat,
    MAX(mat) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS BETWEEN {{STALE_ROWS_PRECEDING}} PRECEDING AND CURRENT ROW)
      - MIN(mat) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS BETWEEN {{STALE_ROWS_PRECEDING}} PRECEDING AND CURRENT ROW) AS span_mat,
    COUNT(zone_t) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS BETWEEN {{STALE_ROWS_PRECEDING}} PRECEDING AND CURRENT ROW) AS n_zone_t,
    MAX(zone_t) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS BETWEEN {{STALE_ROWS_PRECEDING}} PRECEDING AND CURRENT ROW)
      - MIN(zone_t) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS BETWEEN {{STALE_ROWS_PRECEDING}} PRECEDING AND CURRENT ROW) AS span_zone_t,
    COUNT(rat) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS BETWEEN {{STALE_ROWS_PRECEDING}} PRECEDING AND CURRENT ROW) AS n_rat,
    MAX(rat) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS BETWEEN {{STALE_ROWS_PRECEDING}} PRECEDING AND CURRENT ROW)
      - MIN(rat) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS BETWEEN {{STALE_ROWS_PRECEDING}} PRECEDING AND CURRENT ROW) AS span_rat,
    COUNT(sat) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS BETWEEN {{STALE_ROWS_PRECEDING}} PRECEDING AND CURRENT ROW) AS n_sat,
    MAX(sat) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS BETWEEN {{STALE_ROWS_PRECEDING}} PRECEDING AND CURRENT ROW)
      - MIN(sat) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS BETWEEN {{STALE_ROWS_PRECEDING}} PRECEDING AND CURRENT ROW) AS span_sat,
    COUNT(chw_supply_t) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS BETWEEN {{STALE_ROWS_PRECEDING}} PRECEDING AND CURRENT ROW) AS n_chw_supply_t,
    MAX(chw_supply_t) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS BETWEEN {{STALE_ROWS_PRECEDING}} PRECEDING AND CURRENT ROW)
      - MIN(chw_supply_t) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS BETWEEN {{STALE_ROWS_PRECEDING}} PRECEDING AND CURRENT ROW) AS span_chw_supply_t,
    COUNT(chw_return_t) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS BETWEEN {{STALE_ROWS_PRECEDING}} PRECEDING AND CURRENT ROW) AS n_chw_return_t,
    MAX(chw_return_t) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS BETWEEN {{STALE_ROWS_PRECEDING}} PRECEDING AND CURRENT ROW)
      - MIN(chw_return_t) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS BETWEEN {{STALE_ROWS_PRECEDING}} PRECEDING AND CURRENT ROW) AS span_chw_return_t,
    COUNT(hw_supply_t) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS BETWEEN {{STALE_ROWS_PRECEDING}} PRECEDING AND CURRENT ROW) AS n_hw_supply_t,
    MAX(hw_supply_t) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS BETWEEN {{STALE_ROWS_PRECEDING}} PRECEDING AND CURRENT ROW)
      - MIN(hw_supply_t) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS BETWEEN {{STALE_ROWS_PRECEDING}} PRECEDING AND CURRENT ROW) AS span_hw_supply_t,
    COUNT(hw_return_t) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS BETWEEN {{STALE_ROWS_PRECEDING}} PRECEDING AND CURRENT ROW) AS n_hw_return_t,
    MAX(hw_return_t) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS BETWEEN {{STALE_ROWS_PRECEDING}} PRECEDING AND CURRENT ROW)
      - MIN(hw_return_t) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS BETWEEN {{STALE_ROWS_PRECEDING}} PRECEDING AND CURRENT ROW) AS span_hw_return_t,
    COUNT(oa_h) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS BETWEEN {{STALE_ROWS_PRECEDING}} PRECEDING AND CURRENT ROW) AS n_oa_h,
    MAX(oa_h) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS BETWEEN {{STALE_ROWS_PRECEDING}} PRECEDING AND CURRENT ROW)
      - MIN(oa_h) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS BETWEEN {{STALE_ROWS_PRECEDING}} PRECEDING AND CURRENT ROW) AS span_oa_h,
    COUNT(ra_h) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS BETWEEN {{STALE_ROWS_PRECEDING}} PRECEDING AND CURRENT ROW) AS n_ra_h,
    MAX(ra_h) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS BETWEEN {{STALE_ROWS_PRECEDING}} PRECEDING AND CURRENT ROW)
      - MIN(ra_h) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS BETWEEN {{STALE_ROWS_PRECEDING}} PRECEDING AND CURRENT ROW) AS span_ra_h,
    COUNT(zone_rh) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS BETWEEN {{STALE_ROWS_PRECEDING}} PRECEDING AND CURRENT ROW) AS n_zone_rh,
    MAX(zone_rh) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS BETWEEN {{STALE_ROWS_PRECEDING}} PRECEDING AND CURRENT ROW)
      - MIN(zone_rh) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS BETWEEN {{STALE_ROWS_PRECEDING}} PRECEDING AND CURRENT ROW) AS span_zone_rh,
    COUNT(ma_h) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS BETWEEN {{STALE_ROWS_PRECEDING}} PRECEDING AND CURRENT ROW) AS n_ma_h,
    MAX(ma_h) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS BETWEEN {{STALE_ROWS_PRECEDING}} PRECEDING AND CURRENT ROW)
      - MIN(ma_h) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS BETWEEN {{STALE_ROWS_PRECEDING}} PRECEDING AND CURRENT ROW) AS span_ma_h,
    COUNT(sa_h) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS BETWEEN {{STALE_ROWS_PRECEDING}} PRECEDING AND CURRENT ROW) AS n_sa_h,
    MAX(sa_h) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS BETWEEN {{STALE_ROWS_PRECEDING}} PRECEDING AND CURRENT ROW)
      - MIN(sa_h) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS BETWEEN {{STALE_ROWS_PRECEDING}} PRECEDING AND CURRENT ROW) AS span_sa_h
  FROM gated
),
scored AS (
  SELECT
    equipment_id,
    timestamp_utc,
    CASE WHEN n_oa_t >= {{STALE_ROWS}} THEN 1 ELSE 0 END
      + CASE WHEN n_mat >= {{STALE_ROWS}} THEN 1 ELSE 0 END
      + CASE WHEN n_zone_t >= {{STALE_ROWS}} THEN 1 ELSE 0 END
      + CASE WHEN n_rat >= {{STALE_ROWS}} THEN 1 ELSE 0 END
      + CASE WHEN n_sat >= {{STALE_ROWS}} THEN 1 ELSE 0 END
      + CASE WHEN n_chw_supply_t >= {{STALE_ROWS}} THEN 1 ELSE 0 END
      + CASE WHEN n_chw_return_t >= {{STALE_ROWS}} THEN 1 ELSE 0 END
      + CASE WHEN n_hw_supply_t >= {{STALE_ROWS}} THEN 1 ELSE 0 END
      + CASE WHEN n_hw_return_t >= {{STALE_ROWS}} THEN 1 ELSE 0 END
      + CASE WHEN n_oa_h >= {{STALE_ROWS}} THEN 1 ELSE 0 END
      + CASE WHEN n_ra_h >= {{STALE_ROWS}} THEN 1 ELSE 0 END
      + CASE WHEN n_zone_rh >= {{STALE_ROWS}} THEN 1 ELSE 0 END
      + CASE WHEN n_ma_h >= {{STALE_ROWS}} THEN 1 ELSE 0 END
      + CASE WHEN n_sa_h >= {{STALE_ROWS}} THEN 1 ELSE 0 END AS roles_mapped,
    CASE WHEN n_oa_t >= {{STALE_ROWS}} AND span_oa_t <= {{STALE_TOL}} THEN 1 ELSE 0 END
      + CASE WHEN n_mat >= {{STALE_ROWS}} AND span_mat <= {{STALE_TOL}} THEN 1 ELSE 0 END
      + CASE WHEN n_zone_t >= {{STALE_ROWS}} AND span_zone_t <= {{STALE_TOL}} THEN 1 ELSE 0 END
      + CASE WHEN n_rat >= {{STALE_ROWS}} AND span_rat <= {{STALE_TOL}} THEN 1 ELSE 0 END
      + CASE WHEN n_sat >= {{STALE_ROWS}} AND span_sat <= {{STALE_TOL}} THEN 1 ELSE 0 END
      + CASE WHEN n_chw_supply_t >= {{STALE_ROWS}} AND span_chw_supply_t <= {{STALE_TOL}} THEN 1 ELSE 0 END
      + CASE WHEN n_chw_return_t >= {{STALE_ROWS}} AND span_chw_return_t <= {{STALE_TOL}} THEN 1 ELSE 0 END
      + CASE WHEN n_hw_supply_t >= {{STALE_ROWS}} AND span_hw_supply_t <= {{STALE_TOL}} THEN 1 ELSE 0 END
      + CASE WHEN n_hw_return_t >= {{STALE_ROWS}} AND span_hw_return_t <= {{STALE_TOL}} THEN 1 ELSE 0 END
      + CASE WHEN n_oa_h >= {{STALE_ROWS}} AND span_oa_h <= {{STALE_TOL}} THEN 1 ELSE 0 END
      + CASE WHEN n_ra_h >= {{STALE_ROWS}} AND span_ra_h <= {{STALE_TOL}} THEN 1 ELSE 0 END
      + CASE WHEN n_zone_rh >= {{STALE_ROWS}} AND span_zone_rh <= {{STALE_TOL}} THEN 1 ELSE 0 END
      + CASE WHEN n_ma_h >= {{STALE_ROWS}} AND span_ma_h <= {{STALE_TOL}} THEN 1 ELSE 0 END
      + CASE WHEN n_sa_h >= {{STALE_ROWS}} AND span_sa_h <= {{STALE_TOL}} THEN 1 ELSE 0 END AS roles_stale
  FROM win
),
base AS (
  SELECT
    equipment_id,
    timestamp_utc,
    CAST(CASE
      WHEN roles_mapped > 0 AND roles_stale = roles_mapped THEN 1
      ELSE 0
    END AS INT) AS raw_fault
  FROM scored
),
elapsed_hold AS (
  -- Forward sample-and-hold. A gap longer than MAX_GAP_HOURS is unknown:
  -- it is not fault time, not covered time, and it breaks confirmation.
  -- The last sample has no forward interval.
  SELECT
    stepped.*,
    CASE
      WHEN stepped.dt_seconds IS NULL
        OR stepped.dt_seconds <= 0.0
        OR stepped.dt_seconds > ({{MAX_GAP_HOURS}} * 3600.0)
      THEN 0.0
      ELSE stepped.dt_seconds
    END AS held_seconds,
    CASE
      WHEN stepped.dt_seconds > ({{MAX_GAP_HOURS}} * 3600.0) THEN 1
      ELSE 0
    END AS gap_after
  FROM (
    SELECT
      src.*,
      EXTRACT(EPOCH FROM (
        LEAD(src.timestamp_utc) OVER (
          PARTITION BY src.equipment_id ORDER BY src.timestamp_utc
        ) - src.timestamp_utc
      )) AS dt_seconds
    FROM base src
  ) stepped
),
lagged AS (
  SELECT
    *,
    CASE
      WHEN raw_fault = LAG(raw_fault) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc)
       AND COALESCE(LAG(gap_after) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc), 0) = 0
      THEN 0 ELSE 1
    END AS is_new_streak
  FROM elapsed_hold
),
grp AS (
  SELECT
    *,
    SUM(is_new_streak)
      OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS UNBOUNDED PRECEDING) AS streak_id
  FROM lagged
),
ranked AS (
  SELECT
    *,
    SUM(held_seconds) OVER (
      PARTITION BY equipment_id, streak_id ORDER BY timestamp_utc
      ROWS UNBOUNDED PRECEDING
    ) AS streak_elapsed
  FROM grp
),
final AS (
  SELECT
    equipment_id,
    held_seconds,
    CASE WHEN raw_fault = 1 AND streak_elapsed >= {{CONFIRM_SECONDS}} THEN 1 ELSE 0 END AS confirmed
  FROM ranked
)
SELECT
  equipment_id,
  SUM(CASE WHEN confirmed = 1 THEN held_seconds ELSE 0.0 END) / 3600.0 AS fault_hours,
  SUM(held_seconds) / 3600.0 AS covered_hours,
  100.0 * SUM(CASE WHEN confirmed = 1 THEN held_seconds ELSE 0.0 END) / NULLIF(SUM(held_seconds), 0.0) AS fault_pct
FROM final
GROUP BY equipment_id;
```
{% endraw %}

### trim1_duct_static.sql

`sql/fdd/postgres/rules/trim1_duct_static.sql`

{% raw %}
```sql
-- PostgreSQL adaptation. Render numeric template parameters with render_rule.py.
-- Inputs must be scoped to one tenant/site and cadence; see README.md.
-- trim1_duct_static.sql — Duct static trim advisory
-- Pandas trim1: high actual duct static + low VAV pressure-request sum.
-- Prefer duct_static (measured); fall back to duct_static_sp when only SP is mapped.
WITH base AS (
  SELECT
    equipment_id,
    timestamp_utc,
    CAST(CASE
      WHEN COALESCE(duct_static, duct_static_sp) IS NULL THEN 0
      WHEN COALESCE(duct_static, duct_static_sp) > {{DUCT_HI}}
       AND COALESCE(static_reset_request, 0) <= {{REQUEST_LO}} THEN 1
      ELSE 0
    END AS INT) AS raw_fault,
    fan_cmd,
    fan_status,
    CASE
      WHEN fan_status IS NOT NULL THEN CASE WHEN fan_status > 0.05 THEN 1 ELSE 0 END
      WHEN fan_cmd IS NOT NULL THEN CASE WHEN (CASE WHEN fan_cmd > 1.0 THEN fan_cmd / 100.0 ELSE fan_cmd END) > 0.01 THEN 1 ELSE 0 END
      ELSE 1
    END AS fan_on

  FROM history
),
elapsed_hold AS (
  -- Forward sample-and-hold. A gap longer than MAX_GAP_HOURS is unknown:
  -- it is not fault time, not covered time, and it breaks confirmation.
  -- The last sample has no forward interval.
  SELECT
    stepped.*,
    CASE
      WHEN stepped.dt_seconds IS NULL
        OR stepped.dt_seconds <= 0.0
        OR stepped.dt_seconds > ({{MAX_GAP_HOURS}} * 3600.0)
      THEN 0.0
      ELSE stepped.dt_seconds
    END AS held_seconds,
    CASE
      WHEN stepped.dt_seconds > ({{MAX_GAP_HOURS}} * 3600.0) THEN 1
      ELSE 0
    END AS gap_after
  FROM (
    SELECT
      src.*,
      EXTRACT(EPOCH FROM (
        LEAD(src.timestamp_utc) OVER (
          PARTITION BY src.equipment_id ORDER BY src.timestamp_utc
        ) - src.timestamp_utc
      )) AS dt_seconds
    FROM base src
  ) stepped
),
lagged AS (
  SELECT
    *,
    CASE
      WHEN raw_fault = LAG(raw_fault) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc)
       AND COALESCE(LAG(gap_after) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc), 0) = 0
      THEN 0 ELSE 1
    END AS is_new_streak
  FROM elapsed_hold
),
grp AS (
  SELECT
    *,
    SUM(is_new_streak)
      OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS UNBOUNDED PRECEDING) AS streak_id
  FROM lagged
),
ranked AS (
  SELECT
    *,
    SUM(held_seconds) OVER (
      PARTITION BY equipment_id, streak_id ORDER BY timestamp_utc
      ROWS UNBOUNDED PRECEDING
    ) AS streak_elapsed
  FROM grp
),
final AS (
  SELECT
    equipment_id,
    held_seconds,
    CASE WHEN raw_fault = 1 AND streak_elapsed >= {{CONFIRM_SECONDS}} THEN 1 ELSE 0 END AS confirmed
  FROM ranked
)
SELECT
  equipment_id,
  SUM(CASE WHEN confirmed = 1 THEN held_seconds ELSE 0.0 END) / 3600.0 AS fault_hours,
  SUM(held_seconds) / 3600.0 AS covered_hours,
  100.0 * SUM(CASE WHEN confirmed = 1 THEN held_seconds ELSE 0.0 END) / NULLIF(SUM(held_seconds), 0.0) AS fault_pct
FROM final
GROUP BY equipment_id;
```
{% endraw %}

### trim3_hwst.sql

`sql/fdd/postgres/rules/trim3_hwst.sql`

{% raw %}
```sql
-- PostgreSQL adaptation. Render numeric template parameters with render_rule.py.
-- Inputs must be scoped to one tenant/site and cadence; see README.md.
-- trim3_hwst.sql — HWST trim advisory
WITH h AS (
  SELECT
    equipment_id,
    timestamp_utc,
    hw_supply_t,
    hw_reset_request_sum,
    pump_status,
    chiller_status,
    chw_flow,
    chw_pump_cmd,
    CASE
      WHEN pump_status IS NOT NULL THEN CASE WHEN pump_status > 0.05 THEN 1 ELSE 0 END
      WHEN chiller_status IS NOT NULL THEN CASE WHEN chiller_status > 0.05 THEN 1 ELSE 0 END
      WHEN chw_flow IS NOT NULL THEN CASE WHEN chw_flow > 1.0 THEN 1 ELSE 0 END
      WHEN chw_pump_cmd IS NOT NULL THEN CASE WHEN (CASE WHEN chw_pump_cmd > 1.0 THEN chw_pump_cmd / 100.0 ELSE chw_pump_cmd END) > 0.05 THEN 1 ELSE 0 END
      ELSE 0
    END AS proof_on
  FROM history
),
base AS (
  SELECT
    equipment_id,
    timestamp_utc,
    CAST(CASE
      WHEN COALESCE(proof_on, 0) = 0 THEN 0
      WHEN hw_supply_t IS NULL THEN 0
      WHEN hw_supply_t > {{HWST_HI}}
       AND COALESCE(hw_reset_request_sum, 0) <= {{REQUEST_LO}} THEN 1
      ELSE 0
    END AS INT) AS raw_fault
  FROM h
),
elapsed_hold AS (
  -- Forward sample-and-hold. A gap longer than MAX_GAP_HOURS is unknown:
  -- it is not fault time, not covered time, and it breaks confirmation.
  -- The last sample has no forward interval.
  SELECT
    stepped.*,
    CASE
      WHEN stepped.dt_seconds IS NULL
        OR stepped.dt_seconds <= 0.0
        OR stepped.dt_seconds > ({{MAX_GAP_HOURS}} * 3600.0)
      THEN 0.0
      ELSE stepped.dt_seconds
    END AS held_seconds,
    CASE
      WHEN stepped.dt_seconds > ({{MAX_GAP_HOURS}} * 3600.0) THEN 1
      ELSE 0
    END AS gap_after
  FROM (
    SELECT
      src.*,
      EXTRACT(EPOCH FROM (
        LEAD(src.timestamp_utc) OVER (
          PARTITION BY src.equipment_id ORDER BY src.timestamp_utc
        ) - src.timestamp_utc
      )) AS dt_seconds
    FROM base src
  ) stepped
),
lagged AS (
  SELECT
    *,
    CASE
      WHEN raw_fault = LAG(raw_fault) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc)
       AND COALESCE(LAG(gap_after) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc), 0) = 0
      THEN 0 ELSE 1
    END AS is_new_streak
  FROM elapsed_hold
),
grp AS (
  SELECT
    *,
    SUM(is_new_streak)
      OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS UNBOUNDED PRECEDING) AS streak_id
  FROM lagged
),
ranked AS (
  SELECT
    *,
    SUM(held_seconds) OVER (
      PARTITION BY equipment_id, streak_id ORDER BY timestamp_utc
      ROWS UNBOUNDED PRECEDING
    ) AS streak_elapsed
  FROM grp
),
final AS (
  SELECT
    equipment_id,
    held_seconds,
    CASE WHEN raw_fault = 1 AND streak_elapsed >= {{CONFIRM_SECONDS}} THEN 1 ELSE 0 END AS confirmed
  FROM ranked
)
SELECT
  equipment_id,
  SUM(CASE WHEN confirmed = 1 THEN held_seconds ELSE 0.0 END) / 3600.0 AS fault_hours,
  SUM(held_seconds) / 3600.0 AS covered_hours,
  100.0 * SUM(CASE WHEN confirmed = 1 THEN held_seconds ELSE 0.0 END) / NULLIF(SUM(held_seconds), 0.0) AS fault_pct
FROM final
GROUP BY equipment_id;
```
{% endraw %}

### trim4_chw_reset.sql

`sql/fdd/postgres/rules/trim4_chw_reset.sql`

{% raw %}
```sql
-- PostgreSQL adaptation. Render numeric template parameters with render_rule.py.
-- Inputs must be scoped to one tenant/site and cadence; see README.md.
-- trim4_chw_reset.sql — CHW plant reset advisory
WITH h AS (
  SELECT
    equipment_id,
    timestamp_utc,
    chw_supply_t,
    chw_reset_request_sum,
    pump_status,
    chiller_status,
    chw_flow,
    chw_pump_cmd,
    CASE
      WHEN pump_status IS NOT NULL THEN CASE WHEN pump_status > 0.05 THEN 1 ELSE 0 END
      WHEN chiller_status IS NOT NULL THEN CASE WHEN chiller_status > 0.05 THEN 1 ELSE 0 END
      WHEN chw_flow IS NOT NULL THEN CASE WHEN chw_flow > 1.0 THEN 1 ELSE 0 END
      WHEN chw_pump_cmd IS NOT NULL THEN CASE WHEN (CASE WHEN chw_pump_cmd > 1.0 THEN chw_pump_cmd / 100.0 ELSE chw_pump_cmd END) > 0.05 THEN 1 ELSE 0 END
      ELSE 0
    END AS proof_on
  FROM history
),
base AS (
  SELECT
    equipment_id,
    timestamp_utc,
    CAST(CASE
      WHEN COALESCE(proof_on, 0) = 0 THEN 0
      WHEN chw_supply_t IS NULL THEN 0
      WHEN chw_supply_t < {{CHW_LO}}
       AND COALESCE(chw_reset_request_sum, 0) <= {{REQUEST_LO}} THEN 1
      ELSE 0
    END AS INT) AS raw_fault
  FROM h
),
elapsed_hold AS (
  -- Forward sample-and-hold. A gap longer than MAX_GAP_HOURS is unknown:
  -- it is not fault time, not covered time, and it breaks confirmation.
  -- The last sample has no forward interval.
  SELECT
    stepped.*,
    CASE
      WHEN stepped.dt_seconds IS NULL
        OR stepped.dt_seconds <= 0.0
        OR stepped.dt_seconds > ({{MAX_GAP_HOURS}} * 3600.0)
      THEN 0.0
      ELSE stepped.dt_seconds
    END AS held_seconds,
    CASE
      WHEN stepped.dt_seconds > ({{MAX_GAP_HOURS}} * 3600.0) THEN 1
      ELSE 0
    END AS gap_after
  FROM (
    SELECT
      src.*,
      EXTRACT(EPOCH FROM (
        LEAD(src.timestamp_utc) OVER (
          PARTITION BY src.equipment_id ORDER BY src.timestamp_utc
        ) - src.timestamp_utc
      )) AS dt_seconds
    FROM base src
  ) stepped
),
lagged AS (
  SELECT
    *,
    CASE
      WHEN raw_fault = LAG(raw_fault) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc)
       AND COALESCE(LAG(gap_after) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc), 0) = 0
      THEN 0 ELSE 1
    END AS is_new_streak
  FROM elapsed_hold
),
grp AS (
  SELECT
    *,
    SUM(is_new_streak)
      OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS UNBOUNDED PRECEDING) AS streak_id
  FROM lagged
),
ranked AS (
  SELECT
    *,
    SUM(held_seconds) OVER (
      PARTITION BY equipment_id, streak_id ORDER BY timestamp_utc
      ROWS UNBOUNDED PRECEDING
    ) AS streak_elapsed
  FROM grp
),
final AS (
  SELECT
    equipment_id,
    held_seconds,
    CASE WHEN raw_fault = 1 AND streak_elapsed >= {{CONFIRM_SECONDS}} THEN 1 ELSE 0 END AS confirmed
  FROM ranked
)
SELECT
  equipment_id,
  SUM(CASE WHEN confirmed = 1 THEN held_seconds ELSE 0.0 END) / 3600.0 AS fault_hours,
  SUM(held_seconds) / 3600.0 AS covered_hours,
  100.0 * SUM(CASE WHEN confirmed = 1 THEN held_seconds ELSE 0.0 END) / NULLIF(SUM(held_seconds), 0.0) AS fault_pct
FROM final
GROUP BY equipment_id;
```
{% endraw %}

### util_interval_fault.sql

`sql/fdd/postgres/rules/util_interval_fault.sql`

{% raw %}
```sql
-- PostgreSQL adaptation. Render numeric template parameters with render_rule.py.
-- Inputs must be scoped to one tenant/site and cadence; see README.md.
-- util_interval_fault.sql — BAS 15m vs utility interval (rolling MAE proxy)
WITH bas_raw AS (
  SELECT
    timestamp_utc,
    kwh,
    electric_kw,
    EXTRACT(EPOCH FROM (
      LEAD(timestamp_utc) OVER (ORDER BY timestamp_utc) - timestamp_utc
    )) AS dt_seconds
  FROM history
  WHERE kwh IS NOT NULL OR electric_kw IS NOT NULL
),
bas AS (
  SELECT
    timestamp_utc,
    COALESCE(
      CAST(kwh AS DOUBLE PRECISION),
      CASE
        WHEN dt_seconds > 0.0 AND dt_seconds <= ({{MAX_GAP_HOURS}} * 3600.0)
        THEN CAST(electric_kw AS DOUBLE PRECISION) * dt_seconds / 3600.0
        ELSE 0.0
      END
    ) AS bas_kwh
  FROM bas_raw
),
util AS (
  SELECT
    timestamp_utc,
    CAST(kwh AS DOUBLE PRECISION) AS util_kwh
  FROM utility_interval
  WHERE kwh IS NOT NULL
),
joined AS (
  SELECT
    b.timestamp_utc,
    ABS(COALESCE(b.bas_kwh, 0.0) - COALESCE(u.util_kwh, 0.0)) AS abs_err
  FROM bas b
  INNER JOIN util u ON b.timestamp_utc = u.timestamp_utc
),
agg AS (
  SELECT
  AVG(abs_err) AS mae
  FROM joined
)
SELECT
  '__UTIL_INTERVAL__' AS equipment_id,
  CASE
    WHEN (SELECT COUNT(*) FROM util) = 0 THEN 0.0
    WHEN mae > {{UTIL_INTERVAL_MAE}} THEN 720.0
    ELSE 0.0
  END AS fault_hours,
  NULL::double precision AS covered_hours,
  NULL::double precision AS fault_pct
FROM agg;
```
{% endraw %}

### util_monthly_fault.sql

`sql/fdd/postgres/rules/util_monthly_fault.sql`

{% raw %}
```sql
-- PostgreSQL adaptation. Render numeric template parameters with render_rule.py.
-- Inputs must be scoped to one tenant/site and cadence; see README.md.
-- util_monthly_fault.sql — BAS monthly kWh vs utility monthly bills (% deviation)
WITH bas_raw AS (
  SELECT
    timestamp_utc,
    kwh,
    electric_kw,
    EXTRACT(EPOCH FROM (
      LEAD(timestamp_utc) OVER (ORDER BY timestamp_utc) - timestamp_utc
    )) AS dt_seconds
  FROM history
  WHERE kwh IS NOT NULL OR electric_kw IS NOT NULL
),
bas_monthly AS (
  SELECT
    to_char(timestamp_utc AT TIME ZONE 'UTC', 'YYYY-MM') AS billing_period,
    SUM(
      COALESCE(
        CAST(kwh AS DOUBLE PRECISION),
        CASE
          WHEN dt_seconds > 0.0 AND dt_seconds <= ({{MAX_GAP_HOURS}} * 3600.0)
          THEN CAST(electric_kw AS DOUBLE PRECISION) * dt_seconds / 3600.0
          ELSE 0.0
        END,
        0.0
      )
    ) AS bas_kwh
  FROM bas_raw
  GROUP BY 1
),
util AS (
  SELECT
    billing_period,
    CAST(kwh AS DOUBLE PRECISION) AS util_kwh
  FROM utility_monthly
  WHERE kwh IS NOT NULL
),
joined AS (
  SELECT
    u.billing_period,
    u.util_kwh,
    COALESCE(b.bas_kwh, 0.0) AS bas_kwh,
    CASE
      WHEN u.util_kwh IS NULL OR u.util_kwh <= 0 THEN 0
      WHEN ABS(COALESCE(b.bas_kwh, 0.0) - u.util_kwh) / u.util_kwh * 100.0 > {{UTIL_PCT_ERR}}
      THEN 1
      ELSE 0
    END AS raw_fault
  FROM util u
  LEFT JOIN bas_monthly b ON b.billing_period = u.billing_period
)
SELECT
  '__UTIL_MONTHLY__' AS equipment_id,
  CAST(SUM(raw_fault) AS DOUBLE PRECISION) * 720.0 AS fault_hours,
  NULL::double precision AS covered_hours,
  NULL::double precision AS fault_pct
FROM joined;
```
{% endraw %}

### vav1_comfort_fault.sql

`sql/fdd/postgres/rules/vav1_comfort_fault.sql`

{% raw %}
```sql
-- PostgreSQL adaptation. Render numeric template parameters with render_rule.py.
-- Inputs must be scoped to one tenant/site and cadence; see README.md.
-- vav1_comfort_fault.sql — zone comfort band with confirm window (Open-FDD parity)
-- When occ_mode is present, require_occupied (default 1) scores the band only
-- while occupied. The rule runner fills a missing or blank occ_mode from the
-- saved Overview calendar (session occupancy_schedule). NULL occ_mode means
-- neither a BAS occupied point nor that calendar is set. Unoccupied setback
-- stays on VAV-2.
-- OFDD-065: do not reference fan_cmd here. Zone-only parquet schemas
-- often lack fan_cmd; PostgreSQL then schema-errors → SKIPPED_MISSING_ROLES.
WITH h AS (
  SELECT
    equipment_id,
    timestamp_utc,
    zone_t,
    occ_mode,
    CAST(CASE WHEN zone_t < {{ZONE_T_LO}} OR zone_t > {{ZONE_T_HI}} THEN 1 ELSE 0 END AS INT) AS band_fault
  FROM history
  WHERE zone_t IS NOT NULL
),
base AS (
  SELECT
    equipment_id,
    timestamp_utc,
    CAST(CASE
      WHEN {{REQUIRE_OCCUPIED}} >= 0.5
       AND occ_mode IS NOT NULL
       AND (
         LOWER(trim(CAST(occ_mode AS VARCHAR))) IN
           ('unoccupied','unocc','off','false','night','standby','setback','no')
         OR (
           fdd.try_double(trim(CAST(occ_mode AS VARCHAR))) IS NOT NULL
           AND fdd.try_double(trim(CAST(occ_mode AS VARCHAR))) <= 0.05
         )
       )
      THEN 0
      ELSE band_fault
    END AS INT) AS raw_fault
  FROM h
),
elapsed_hold AS (
  -- Forward sample-and-hold. A gap longer than MAX_GAP_HOURS is unknown:
  -- it is not fault time, not covered time, and it breaks confirmation.
  -- The last sample has no forward interval.
  SELECT
    stepped.*,
    CASE
      WHEN stepped.dt_seconds IS NULL
        OR stepped.dt_seconds <= 0.0
        OR stepped.dt_seconds > ({{MAX_GAP_HOURS}} * 3600.0)
      THEN 0.0
      ELSE stepped.dt_seconds
    END AS held_seconds,
    CASE
      WHEN stepped.dt_seconds > ({{MAX_GAP_HOURS}} * 3600.0) THEN 1
      ELSE 0
    END AS gap_after
  FROM (
    SELECT
      src.*,
      EXTRACT(EPOCH FROM (
        LEAD(src.timestamp_utc) OVER (
          PARTITION BY src.equipment_id ORDER BY src.timestamp_utc
        ) - src.timestamp_utc
      )) AS dt_seconds
    FROM base src
  ) stepped
),
lagged AS (
  SELECT
    *,
    CASE
      WHEN raw_fault = LAG(raw_fault) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc)
       AND COALESCE(LAG(gap_after) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc), 0) = 0
      THEN 0 ELSE 1
    END AS is_new_streak
  FROM elapsed_hold
),
grp AS (
  SELECT
    *,
    SUM(is_new_streak)
      OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS UNBOUNDED PRECEDING) AS streak_id
  FROM lagged
),
ranked AS (
  SELECT
    *,
    SUM(held_seconds) OVER (
      PARTITION BY equipment_id, streak_id ORDER BY timestamp_utc
      ROWS UNBOUNDED PRECEDING
    ) AS streak_elapsed
  FROM grp
),
final AS (
  SELECT
    equipment_id,
    held_seconds,
    timestamp_utc,
    CASE WHEN raw_fault = 1 AND streak_elapsed >= {{CONFIRM_SECONDS}} THEN 1 ELSE 0 END AS confirmed
  FROM ranked
)
SELECT
  equipment_id,
  SUM(CASE WHEN confirmed = 1 THEN held_seconds ELSE 0.0 END) / 3600.0 AS fault_hours,
  SUM(held_seconds) / 3600.0 AS covered_hours,
  100.0 * SUM(CASE WHEN confirmed = 1 THEN held_seconds ELSE 0.0 END) / NULLIF(SUM(held_seconds), 0.0) AS fault_pct
FROM final
GROUP BY equipment_id;
```
{% endraw %}

### vav2_night_setback.sql

`sql/fdd/postgres/rules/vav2_night_setback.sql`

{% raw %}
```sql
-- PostgreSQL adaptation. Render numeric template parameters with render_rule.py.
-- Inputs must be scoped to one tenant/site and cadence; see README.md.
-- vav2_night_setback.sql — unoccupied zone stays above heating setback
-- Occupied hours do not latch. Missing occ_mode → no unoccupied proof (no fault).
WITH h AS (
  SELECT
    equipment_id,
    timestamp_utc,
    zone_t,
    occ_mode,
    CAST(CASE
      WHEN occ_mode IS NULL THEN 0
      WHEN (
        LOWER(trim(CAST(occ_mode AS VARCHAR))) IN
          ('unoccupied','unocc','off','false','night','standby','setback','0','0.0','no')
        OR (
          fdd.try_double(trim(CAST(occ_mode AS VARCHAR))) IS NOT NULL
          AND fdd.try_double(trim(CAST(occ_mode AS VARCHAR))) <= 0.05
        )
      )
       AND zone_t IS NOT NULL AND zone_t > {{SETBACK_HI}} THEN 1
      ELSE 0
    END AS INT) AS raw_fault
  FROM history
),
elapsed_hold AS (
  -- Forward sample-and-hold. A gap longer than MAX_GAP_HOURS is unknown:
  -- it is not fault time, not covered time, and it breaks confirmation.
  -- The last sample has no forward interval.
  SELECT
    stepped.*,
    CASE
      WHEN stepped.dt_seconds IS NULL
        OR stepped.dt_seconds <= 0.0
        OR stepped.dt_seconds > ({{MAX_GAP_HOURS}} * 3600.0)
      THEN 0.0
      ELSE stepped.dt_seconds
    END AS held_seconds,
    CASE
      WHEN stepped.dt_seconds > ({{MAX_GAP_HOURS}} * 3600.0) THEN 1
      ELSE 0
    END AS gap_after
  FROM (
    SELECT
      src.*,
      EXTRACT(EPOCH FROM (
        LEAD(src.timestamp_utc) OVER (
          PARTITION BY src.equipment_id ORDER BY src.timestamp_utc
        ) - src.timestamp_utc
      )) AS dt_seconds
    FROM h src
  ) stepped
),
lagged AS (
  SELECT
    *,
    CASE
      WHEN raw_fault = LAG(raw_fault) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc)
       AND COALESCE(LAG(gap_after) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc), 0) = 0
      THEN 0 ELSE 1
    END AS is_new_streak
  FROM elapsed_hold
),
grp AS (
  SELECT
    *,
    SUM(is_new_streak)
      OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS UNBOUNDED PRECEDING) AS streak_id
  FROM lagged
),
ranked AS (
  SELECT
    *,
    SUM(held_seconds) OVER (
      PARTITION BY equipment_id, streak_id ORDER BY timestamp_utc
      ROWS UNBOUNDED PRECEDING
    ) AS streak_elapsed
  FROM grp
),
final AS (
  SELECT
    equipment_id,
    held_seconds,
    CASE WHEN raw_fault = 1 AND streak_elapsed >= {{CONFIRM_SECONDS}} THEN 1 ELSE 0 END AS confirmed
  FROM ranked
)
SELECT
  equipment_id,
  SUM(CASE WHEN confirmed = 1 THEN held_seconds ELSE 0.0 END) / 3600.0 AS fault_hours,
  SUM(held_seconds) / 3600.0 AS covered_hours,
  100.0 * SUM(CASE WHEN confirmed = 1 THEN held_seconds ELSE 0.0 END) / NULLIF(SUM(held_seconds), 0.0) AS fault_pct
FROM final
GROUP BY equipment_id;
```
{% endraw %}

### vav3_excessive_reheat.sql

`sql/fdd/postgres/rules/vav3_excessive_reheat.sql`

{% raw %}
```sql
-- PostgreSQL adaptation. Render numeric template parameters with render_rule.py.
-- Inputs must be scoped to one tenant/site and cadence; see README.md.
-- vav3_excessive_reheat.sql — Excessive reheat during warm weather
WITH h AS (
  SELECT
    equipment_id,
    timestamp_utc,
    oa_t, zone_flow,
    CASE WHEN reheat_valve_pct IS NULL THEN NULL WHEN reheat_valve_pct > 1.0 THEN reheat_valve_pct / 100.0 ELSE reheat_valve_pct END AS rh,
    fan_cmd,
    fan_status,
    CASE
      WHEN fan_status IS NOT NULL THEN CASE WHEN fan_status > 0.05 THEN 1 ELSE 0 END
      WHEN fan_cmd IS NOT NULL THEN CASE WHEN (CASE WHEN fan_cmd > 1.0 THEN fan_cmd / 100.0 ELSE fan_cmd END) > 0.01 THEN 1 ELSE 0 END
      ELSE 1
    END AS fan_on

  FROM history
),
base AS (
  SELECT
    equipment_id,
    timestamp_utc,
    CAST(CASE
      WHEN COALESCE(fan_on, 0) = 0 THEN 0
      WHEN oa_t IS NULL OR rh IS NULL THEN 0
      WHEN COALESCE(zone_flow, 0) > {{FLOW_ON_MIN}}
       AND oa_t > {{REHEAT_OAT}} AND rh > {{REHEAT_PCT}} THEN 1
      ELSE 0
    END AS INT) AS raw_fault
  FROM h
),
elapsed_hold AS (
  -- Forward sample-and-hold. A gap longer than MAX_GAP_HOURS is unknown:
  -- it is not fault time, not covered time, and it breaks confirmation.
  -- The last sample has no forward interval.
  SELECT
    stepped.*,
    CASE
      WHEN stepped.dt_seconds IS NULL
        OR stepped.dt_seconds <= 0.0
        OR stepped.dt_seconds > ({{MAX_GAP_HOURS}} * 3600.0)
      THEN 0.0
      ELSE stepped.dt_seconds
    END AS held_seconds,
    CASE
      WHEN stepped.dt_seconds > ({{MAX_GAP_HOURS}} * 3600.0) THEN 1
      ELSE 0
    END AS gap_after
  FROM (
    SELECT
      src.*,
      EXTRACT(EPOCH FROM (
        LEAD(src.timestamp_utc) OVER (
          PARTITION BY src.equipment_id ORDER BY src.timestamp_utc
        ) - src.timestamp_utc
      )) AS dt_seconds
    FROM base src
  ) stepped
),
lagged AS (
  SELECT
    *,
    CASE
      WHEN raw_fault = LAG(raw_fault) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc)
       AND COALESCE(LAG(gap_after) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc), 0) = 0
      THEN 0 ELSE 1
    END AS is_new_streak
  FROM elapsed_hold
),
grp AS (
  SELECT
    *,
    SUM(is_new_streak)
      OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS UNBOUNDED PRECEDING) AS streak_id
  FROM lagged
),
ranked AS (
  SELECT
    *,
    SUM(held_seconds) OVER (
      PARTITION BY equipment_id, streak_id ORDER BY timestamp_utc
      ROWS UNBOUNDED PRECEDING
    ) AS streak_elapsed
  FROM grp
),
final AS (
  SELECT
    equipment_id,
    held_seconds,
    CASE WHEN raw_fault = 1 AND streak_elapsed >= {{CONFIRM_SECONDS}} THEN 1 ELSE 0 END AS confirmed
  FROM ranked
)
SELECT
  equipment_id,
  SUM(CASE WHEN confirmed = 1 THEN held_seconds ELSE 0.0 END) / 3600.0 AS fault_hours,
  SUM(held_seconds) / 3600.0 AS covered_hours,
  100.0 * SUM(CASE WHEN confirmed = 1 THEN held_seconds ELSE 0.0 END) / NULLIF(SUM(held_seconds), 0.0) AS fault_pct
FROM final
GROUP BY equipment_id;
```
{% endraw %}

### vav4_damper_full_open.sql

`sql/fdd/postgres/rules/vav4_damper_full_open.sql`

{% raw %}
```sql
-- PostgreSQL adaptation. Render numeric template parameters with render_rule.py.
-- Inputs must be scoped to one tenant/site and cadence; see README.md.
-- vav4_damper_full_open.sql — sequential sustain then confirm (pandas vav4).
-- Stage 1: air-on and damper > FULL_OPEN for SUSTAIN_HOURS of eligible elapsed time.
-- Stage 2: confirm that sustained mask for CONFIRM_SECONDS (not the max of the two).
-- Gaps longer than MAX_GAP_HOURS are unknown and break both streaks.
WITH h AS (
  SELECT
    equipment_id,
    timestamp_utc,
    zone_flow,
    CASE WHEN damper_pct IS NULL THEN NULL WHEN damper_pct > 1.0 THEN damper_pct / 100.0 ELSE damper_pct END AS dmp,
    fan_cmd,
    fan_status,
    CASE
      WHEN fan_status IS NOT NULL THEN CASE WHEN fan_status > 0.05 THEN 1 ELSE 0 END
      WHEN fan_cmd IS NOT NULL THEN CASE WHEN (CASE WHEN fan_cmd > 1.0 THEN fan_cmd / 100.0 ELSE fan_cmd END) > 0.01 THEN 1 ELSE 0 END
      WHEN zone_flow IS NOT NULL AND zone_flow > {{FLOW_ON_MIN}} THEN 1
      ELSE 1
    END AS fan_on
  FROM history
),
cond AS (
  SELECT
    equipment_id,
    timestamp_utc,
    CAST(CASE
      WHEN COALESCE(fan_on, 0) = 0 THEN 0
      WHEN dmp IS NULL THEN 0
      WHEN COALESCE(zone_flow, 0) > {{FLOW_ON_MIN}} AND dmp > {{FULL_OPEN_PCT}} THEN 1
      ELSE 0
    END AS INT) AS cond_fault
  FROM h
),
elapsed_hold AS (
  SELECT
    stepped.*,
    CASE
      WHEN stepped.dt_seconds IS NULL
        OR stepped.dt_seconds <= 0.0
        OR stepped.dt_seconds > ({{MAX_GAP_HOURS}} * 3600.0)
      THEN 0.0
      ELSE stepped.dt_seconds
    END AS held_seconds,
    CASE
      WHEN stepped.dt_seconds > ({{MAX_GAP_HOURS}} * 3600.0) THEN 1
      ELSE 0
    END AS gap_after
  FROM (
    SELECT
      src.*,
      EXTRACT(EPOCH FROM (
        LEAD(src.timestamp_utc) OVER (
          PARTITION BY src.equipment_id ORDER BY src.timestamp_utc
        ) - src.timestamp_utc
      )) AS dt_seconds
    FROM cond src
  ) stepped
),
lagged1 AS (
  SELECT
    *,
    CASE
      WHEN cond_fault = LAG(cond_fault) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc)
       AND COALESCE(LAG(gap_after) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc), 0) = 0
      THEN 0 ELSE 1
    END AS is_new1
  FROM elapsed_hold
),
grp1 AS (
  SELECT
    *,
    SUM(is_new1) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS UNBOUNDED PRECEDING) AS streak1
  FROM lagged1
),
sustained AS (
  SELECT
    *,
    CAST(CASE
      WHEN cond_fault = 1
       AND SUM(held_seconds) OVER (
         PARTITION BY equipment_id, streak1 ORDER BY timestamp_utc
         ROWS UNBOUNDED PRECEDING
       ) >= ({{SUSTAIN_HOURS}} * 3600.0)
      THEN 1 ELSE 0
    END AS INT) AS sustained_fault
  FROM grp1
),
lagged2 AS (
  SELECT
    *,
    CASE
      WHEN sustained_fault = LAG(sustained_fault) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc)
       AND COALESCE(LAG(gap_after) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc), 0) = 0
      THEN 0 ELSE 1
    END AS is_new2
  FROM sustained
),
grp2 AS (
  SELECT
    *,
    SUM(is_new2) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS UNBOUNDED PRECEDING) AS streak2
  FROM lagged2
),
final AS (
  SELECT
    equipment_id,
    held_seconds,
    CAST(CASE
      WHEN sustained_fault = 1
       AND SUM(held_seconds) OVER (
         PARTITION BY equipment_id, streak2 ORDER BY timestamp_utc
         ROWS UNBOUNDED PRECEDING
       ) >= {{CONFIRM_SECONDS}}
      THEN 1 ELSE 0
    END AS INT) AS confirmed
  FROM grp2
)
SELECT
  equipment_id,
  SUM(CASE WHEN confirmed = 1 THEN held_seconds ELSE 0.0 END) / 3600.0 AS fault_hours,
  SUM(held_seconds) / 3600.0 AS covered_hours,
  100.0 * SUM(CASE WHEN confirmed = 1 THEN held_seconds ELSE 0.0 END) / NULLIF(SUM(held_seconds), 0.0) AS fault_pct
FROM final
GROUP BY equipment_id;
```
{% endraw %}

### vav5_airflow_bias.sql

`sql/fdd/postgres/rules/vav5_airflow_bias.sql`

{% raw %}
```sql
-- PostgreSQL adaptation. Render numeric template parameters with render_rule.py.
-- Inputs must be scoped to one tenant/site and cadence; see README.md.
-- vav5_airflow_bias.sql — Airflow sensor bias
WITH h AS (
  SELECT
    equipment_id,
    timestamp_utc,
    zone_flow,
    CASE WHEN damper_pct IS NULL THEN NULL WHEN damper_pct > 1.0 THEN damper_pct / 100.0 ELSE damper_pct END AS dmp,
    fan_cmd,
    fan_status,
    CASE
      WHEN fan_status IS NOT NULL THEN CASE WHEN fan_status > 0.05 THEN 1 ELSE 0 END
      WHEN fan_cmd IS NOT NULL THEN CASE WHEN (CASE WHEN fan_cmd > 1.0 THEN fan_cmd / 100.0 ELSE fan_cmd END) > 0.01 THEN 1 ELSE 0 END
      ELSE 1
    END AS fan_on

  FROM history
),
base AS (
  SELECT
    equipment_id,
    timestamp_utc,
    CAST(CASE
      WHEN COALESCE(fan_on, 0) = 0 THEN 0
      WHEN zone_flow IS NULL OR dmp IS NULL THEN 0
      WHEN zone_flow > {{FLOW_BIAS_CFM}} AND dmp < {{DAMPER_CLOSED_MAX}} THEN 1
      ELSE 0
    END AS INT) AS raw_fault
  FROM h
),
elapsed_hold AS (
  -- Forward sample-and-hold. A gap longer than MAX_GAP_HOURS is unknown:
  -- it is not fault time, not covered time, and it breaks confirmation.
  -- The last sample has no forward interval.
  SELECT
    stepped.*,
    CASE
      WHEN stepped.dt_seconds IS NULL
        OR stepped.dt_seconds <= 0.0
        OR stepped.dt_seconds > ({{MAX_GAP_HOURS}} * 3600.0)
      THEN 0.0
      ELSE stepped.dt_seconds
    END AS held_seconds,
    CASE
      WHEN stepped.dt_seconds > ({{MAX_GAP_HOURS}} * 3600.0) THEN 1
      ELSE 0
    END AS gap_after
  FROM (
    SELECT
      src.*,
      EXTRACT(EPOCH FROM (
        LEAD(src.timestamp_utc) OVER (
          PARTITION BY src.equipment_id ORDER BY src.timestamp_utc
        ) - src.timestamp_utc
      )) AS dt_seconds
    FROM base src
  ) stepped
),
lagged AS (
  SELECT
    *,
    CASE
      WHEN raw_fault = LAG(raw_fault) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc)
       AND COALESCE(LAG(gap_after) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc), 0) = 0
      THEN 0 ELSE 1
    END AS is_new_streak
  FROM elapsed_hold
),
grp AS (
  SELECT
    *,
    SUM(is_new_streak)
      OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS UNBOUNDED PRECEDING) AS streak_id
  FROM lagged
),
ranked AS (
  SELECT
    *,
    SUM(held_seconds) OVER (
      PARTITION BY equipment_id, streak_id ORDER BY timestamp_utc
      ROWS UNBOUNDED PRECEDING
    ) AS streak_elapsed
  FROM grp
),
final AS (
  SELECT
    equipment_id,
    held_seconds,
    CASE WHEN raw_fault = 1 AND streak_elapsed >= {{CONFIRM_SECONDS}} THEN 1 ELSE 0 END AS confirmed
  FROM ranked
)
SELECT
  equipment_id,
  SUM(CASE WHEN confirmed = 1 THEN held_seconds ELSE 0.0 END) / 3600.0 AS fault_hours,
  SUM(held_seconds) / 3600.0 AS covered_hours,
  100.0 * SUM(CASE WHEN confirmed = 1 THEN held_seconds ELSE 0.0 END) / NULLIF(SUM(held_seconds), 0.0) AS fault_pct
FROM final
GROUP BY equipment_id;
```
{% endraw %}

### vav6_reheat_free_cool.sql

`sql/fdd/postgres/rules/vav6_reheat_free_cool.sql`

{% raw %}
```sql
-- PostgreSQL adaptation. Render numeric template parameters with render_rule.py.
-- Inputs must be scoped to one tenant/site and cadence; see README.md.
-- vav6_reheat_free_cool.sql — reheat open while OA is cool enough for free cooling
WITH h AS (
  SELECT
    equipment_id,
    timestamp_utc,
    oa_t,
    clg_available,
    CASE WHEN reheat_valve_pct IS NULL THEN NULL
         WHEN reheat_valve_pct > 1.0 THEN reheat_valve_pct / 100.0
         ELSE reheat_valve_pct END AS rh
  FROM history
),
base AS (
  SELECT
    equipment_id,
    timestamp_utc,
    CAST(CASE
      WHEN oa_t IS NULL OR rh IS NULL THEN 0
      WHEN COALESCE(clg_available, 1) > 0.05
       AND oa_t < {{FREE_COOL_OAT}} AND rh > {{REHEAT_PCT}} THEN 1
      ELSE 0
    END AS INT) AS raw_fault
  FROM h
),
elapsed_hold AS (
  -- Forward sample-and-hold. A gap longer than MAX_GAP_HOURS is unknown:
  -- it is not fault time, not covered time, and it breaks confirmation.
  -- The last sample has no forward interval.
  SELECT
    stepped.*,
    CASE
      WHEN stepped.dt_seconds IS NULL
        OR stepped.dt_seconds <= 0.0
        OR stepped.dt_seconds > ({{MAX_GAP_HOURS}} * 3600.0)
      THEN 0.0
      ELSE stepped.dt_seconds
    END AS held_seconds,
    CASE
      WHEN stepped.dt_seconds > ({{MAX_GAP_HOURS}} * 3600.0) THEN 1
      ELSE 0
    END AS gap_after
  FROM (
    SELECT
      src.*,
      EXTRACT(EPOCH FROM (
        LEAD(src.timestamp_utc) OVER (
          PARTITION BY src.equipment_id ORDER BY src.timestamp_utc
        ) - src.timestamp_utc
      )) AS dt_seconds
    FROM base src
  ) stepped
),
lagged AS (
  SELECT
    *,
    CASE
      WHEN raw_fault = LAG(raw_fault) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc)
       AND COALESCE(LAG(gap_after) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc), 0) = 0
      THEN 0 ELSE 1
    END AS is_new_streak
  FROM elapsed_hold
),
grp AS (
  SELECT
    *,
    SUM(is_new_streak)
      OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS UNBOUNDED PRECEDING) AS streak_id
  FROM lagged
),
ranked AS (
  SELECT
    *,
    SUM(held_seconds) OVER (
      PARTITION BY equipment_id, streak_id ORDER BY timestamp_utc
      ROWS UNBOUNDED PRECEDING
    ) AS streak_elapsed
  FROM grp
),
final AS (
  SELECT
    equipment_id,
    held_seconds,
    CASE WHEN raw_fault = 1 AND streak_elapsed >= {{CONFIRM_SECONDS}} THEN 1 ELSE 0 END AS confirmed
  FROM ranked
)
SELECT
  equipment_id,
  SUM(CASE WHEN confirmed = 1 THEN held_seconds ELSE 0.0 END) / 3600.0 AS fault_hours,
  SUM(held_seconds) / 3600.0 AS covered_hours,
  100.0 * SUM(CASE WHEN confirmed = 1 THEN held_seconds ELSE 0.0 END) / NULLIF(SUM(held_seconds), 0.0) AS fault_pct
FROM final
GROUP BY equipment_id;
```
{% endraw %}

### vav7_min_airflow.sql

`sql/fdd/postgres/rules/vav7_min_airflow.sql`

{% raw %}
```sql
-- PostgreSQL adaptation. Render numeric template parameters with render_rule.py.
-- Inputs must be scoped to one tenant/site and cadence; see README.md.
-- vav7_min_airflow.sql — three pandas branches: under-min, fixed-high flow, high min SP.
-- Rolling windows use poll-derived {{FIXED_FLOW_ROWS}} (1h sample count), matching pandas.
WITH h AS (
  SELECT
    equipment_id,
    timestamp_utc,
    zone_flow,
    min_flow_sp,
    fan_cmd,
    fan_status,
    CASE
      WHEN fan_status IS NOT NULL THEN CASE WHEN fan_status > 0.05 THEN 1 ELSE 0 END
      WHEN fan_cmd IS NOT NULL THEN CASE WHEN (CASE WHEN fan_cmd > 1.0 THEN fan_cmd / 100.0 ELSE fan_cmd END) > 0.01 THEN 1 ELSE 0 END
      WHEN zone_flow IS NOT NULL AND zone_flow > {{FLOW_ON_MIN}} THEN 1
      ELSE 1
    END AS fan_on
  FROM history
),
rolled AS (
  SELECT
    *,
    STDDEV_SAMP(zone_flow) OVER (
      PARTITION BY equipment_id ORDER BY timestamp_utc
      ROWS BETWEEN {{FIXED_FLOW_ROWS_PRECEDING}} PRECEDING AND CURRENT ROW
    ) AS roll_std,
    AVG(zone_flow) OVER (
      PARTITION BY equipment_id ORDER BY timestamp_utc
      ROWS BETWEEN {{FIXED_FLOW_ROWS_PRECEDING}} PRECEDING AND CURRENT ROW
    ) AS roll_mean,
    COUNT(zone_flow) OVER (
      PARTITION BY equipment_id ORDER BY timestamp_utc
      ROWS BETWEEN {{FIXED_FLOW_ROWS_PRECEDING}} PRECEDING AND CURRENT ROW
    ) AS roll_n
  FROM h
),
base AS (
  SELECT
    equipment_id,
    timestamp_utc,
    CAST(CASE
      WHEN COALESCE(fan_on, 0) = 0 THEN 0
      WHEN zone_flow IS NULL THEN 0
      WHEN min_flow_sp IS NOT NULL AND zone_flow > {{FLOW_ON_MIN}} AND zone_flow < min_flow_sp THEN 1
      WHEN roll_n >= {{FIXED_FLOW_MIN_PERIODS}}
           AND zone_flow IS NOT NULL
           AND roll_std < {{FIXED_FLOW_MAX_STD}}
           AND roll_mean > {{FIXED_FLOW_MIN_MEAN}} THEN 1
      WHEN min_flow_sp IS NOT NULL
           AND roll_n >= {{FIXED_FLOW_MIN_PERIODS}}
           AND min_flow_sp > {{HIGH_MIN_FLOW_SP}}
           AND roll_std < {{FIXED_FLOW_MAX_STD}} THEN 1
      ELSE 0
    END AS INT) AS raw_fault
  FROM rolled
),
elapsed_hold AS (
  -- Forward sample-and-hold. A gap longer than MAX_GAP_HOURS is unknown:
  -- it is not fault time, not covered time, and it breaks confirmation.
  -- The last sample has no forward interval.
  SELECT
    stepped.*,
    CASE
      WHEN stepped.dt_seconds IS NULL
        OR stepped.dt_seconds <= 0.0
        OR stepped.dt_seconds > ({{MAX_GAP_HOURS}} * 3600.0)
      THEN 0.0
      ELSE stepped.dt_seconds
    END AS held_seconds,
    CASE
      WHEN stepped.dt_seconds > ({{MAX_GAP_HOURS}} * 3600.0) THEN 1
      ELSE 0
    END AS gap_after
  FROM (
    SELECT
      src.*,
      EXTRACT(EPOCH FROM (
        LEAD(src.timestamp_utc) OVER (
          PARTITION BY src.equipment_id ORDER BY src.timestamp_utc
        ) - src.timestamp_utc
      )) AS dt_seconds
    FROM base src
  ) stepped
),
lagged AS (
  SELECT
    *,
    CASE
      WHEN raw_fault = LAG(raw_fault) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc)
       AND COALESCE(LAG(gap_after) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc), 0) = 0
      THEN 0 ELSE 1
    END AS is_new_streak
  FROM elapsed_hold
),
grp AS (
  SELECT
    *,
    SUM(is_new_streak)
      OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS UNBOUNDED PRECEDING) AS streak_id
  FROM lagged
),
ranked AS (
  SELECT
    *,
    SUM(held_seconds) OVER (
      PARTITION BY equipment_id, streak_id ORDER BY timestamp_utc
      ROWS UNBOUNDED PRECEDING
    ) AS streak_elapsed
  FROM grp
),
final AS (
  SELECT
    equipment_id,
    held_seconds,
    CASE WHEN raw_fault = 1 AND streak_elapsed >= {{CONFIRM_SECONDS}} THEN 1 ELSE 0 END AS confirmed
  FROM ranked
)
SELECT
  equipment_id,
  SUM(CASE WHEN confirmed = 1 THEN held_seconds ELSE 0.0 END) / 3600.0 AS fault_hours,
  SUM(held_seconds) / 3600.0 AS covered_hours,
  100.0 * SUM(CASE WHEN confirmed = 1 THEN held_seconds ELSE 0.0 END) / NULLIF(SUM(held_seconds), 0.0) AS fault_pct
FROM final
GROUP BY equipment_id;
```
{% endraw %}

### vav_ahu_leave.sql

`sql/fdd/postgres/rules/vav_ahu_leave.sql`

{% raw %}
```sql
-- PostgreSQL adaptation. Render numeric template parameters with render_rule.py.
-- Inputs must be scoped to one tenant/site and cadence; see README.md.
-- vav_ahu_leave.sql — VAV leave vs parent AHU SAT (fedBy)
WITH h AS (
  SELECT
    equipment_id,
    timestamp_utc,
    vav_discharge_t,
    ahu_sat,
    zone_flow,
    fan_cmd,
    fan_status,
    CASE
      WHEN fan_status IS NOT NULL THEN CASE WHEN fan_status > 0.05 THEN 1 ELSE 0 END
      WHEN fan_cmd IS NOT NULL THEN CASE WHEN (CASE WHEN fan_cmd > 1.0 THEN fan_cmd / 100.0 ELSE fan_cmd END) > 0.01 THEN 1 ELSE 0 END
      ELSE 1
    END AS fan_on
  FROM history
),
base AS (
  SELECT
    equipment_id,
    timestamp_utc,
    CAST(CASE
      WHEN COALESCE(fan_on, 0) = 0 THEN 0
      WHEN vav_discharge_t IS NULL OR ahu_sat IS NULL THEN 0
      WHEN COALESCE(zone_flow, 0) > {{FLOW_ON_MIN}}
       AND ABS(vav_discharge_t - ahu_sat) > {{DELTA_F}} THEN 1
      ELSE 0
    END AS INT) AS raw_fault
  FROM h
),
elapsed_hold AS (
  -- Forward sample-and-hold. A gap longer than MAX_GAP_HOURS is unknown:
  -- it is not fault time, not covered time, and it breaks confirmation.
  -- The last sample has no forward interval.
  SELECT
    stepped.*,
    CASE
      WHEN stepped.dt_seconds IS NULL
        OR stepped.dt_seconds <= 0.0
        OR stepped.dt_seconds > ({{MAX_GAP_HOURS}} * 3600.0)
      THEN 0.0
      ELSE stepped.dt_seconds
    END AS held_seconds,
    CASE
      WHEN stepped.dt_seconds > ({{MAX_GAP_HOURS}} * 3600.0) THEN 1
      ELSE 0
    END AS gap_after
  FROM (
    SELECT
      src.*,
      EXTRACT(EPOCH FROM (
        LEAD(src.timestamp_utc) OVER (
          PARTITION BY src.equipment_id ORDER BY src.timestamp_utc
        ) - src.timestamp_utc
      )) AS dt_seconds
    FROM base src
  ) stepped
),
lagged AS (
  SELECT
    *,
    CASE
      WHEN raw_fault = LAG(raw_fault) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc)
       AND COALESCE(LAG(gap_after) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc), 0) = 0
      THEN 0 ELSE 1
    END AS is_new_streak
  FROM elapsed_hold
),
grp AS (
  SELECT
    *,
    SUM(is_new_streak)
      OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS UNBOUNDED PRECEDING) AS streak_id
  FROM lagged
),
ranked AS (
  SELECT
    *,
    SUM(held_seconds) OVER (
      PARTITION BY equipment_id, streak_id ORDER BY timestamp_utc
      ROWS UNBOUNDED PRECEDING
    ) AS streak_elapsed
  FROM grp
),
final AS (
  SELECT
    equipment_id,
    held_seconds,
    CASE WHEN raw_fault = 1 AND streak_elapsed >= {{CONFIRM_SECONDS}} THEN 1 ELSE 0 END AS confirmed
  FROM ranked
)
SELECT
  equipment_id,
  SUM(CASE WHEN confirmed = 1 THEN held_seconds ELSE 0.0 END) / 3600.0 AS fault_hours,
  SUM(held_seconds) / 3600.0 AS covered_hours,
  100.0 * SUM(CASE WHEN confirmed = 1 THEN held_seconds ELSE 0.0 END) / NULLIF(SUM(held_seconds), 0.0) AS fault_pct
FROM final
GROUP BY equipment_id;
```
{% endraw %}

### vav_reheat.sql

`sql/fdd/postgres/rules/vav_reheat.sql`

{% raw %}
```sql
-- PostgreSQL adaptation. Render numeric template parameters with render_rule.py.
-- Inputs must be scoped to one tenant/site and cadence; see README.md.
-- vav_reheat.sql — Reheat valve stuck / no temp rise
WITH h AS (
  SELECT
    equipment_id,
    timestamp_utc,
    vav_discharge_t, vav_inlet_t, zone_flow,
    CASE WHEN reheat_valve_pct IS NULL THEN NULL WHEN reheat_valve_pct > 1.0 THEN reheat_valve_pct / 100.0 ELSE reheat_valve_pct END AS rh,
    fan_cmd,
    fan_status,
    CASE
      WHEN fan_status IS NOT NULL THEN CASE WHEN fan_status > 0.05 THEN 1 ELSE 0 END
      WHEN fan_cmd IS NOT NULL THEN CASE WHEN (CASE WHEN fan_cmd > 1.0 THEN fan_cmd / 100.0 ELSE fan_cmd END) > 0.01 THEN 1 ELSE 0 END
      ELSE 1
    END AS fan_on

  FROM history
),
base AS (
  SELECT
    equipment_id,
    timestamp_utc,
    CAST(CASE
      WHEN COALESCE(fan_on, 0) = 0 THEN 0
      WHEN rh IS NULL OR vav_discharge_t IS NULL OR vav_inlet_t IS NULL THEN 0
      WHEN COALESCE(zone_flow, 0) > {{FLOW_ON_MIN}}
       AND rh > {{REHEAT_CMD}}
       AND (vav_discharge_t - vav_inlet_t) < {{MIN_RISE}} THEN 1
      ELSE 0
    END AS INT) AS raw_fault
  FROM h
),
elapsed_hold AS (
  -- Forward sample-and-hold. A gap longer than MAX_GAP_HOURS is unknown:
  -- it is not fault time, not covered time, and it breaks confirmation.
  -- The last sample has no forward interval.
  SELECT
    stepped.*,
    CASE
      WHEN stepped.dt_seconds IS NULL
        OR stepped.dt_seconds <= 0.0
        OR stepped.dt_seconds > ({{MAX_GAP_HOURS}} * 3600.0)
      THEN 0.0
      ELSE stepped.dt_seconds
    END AS held_seconds,
    CASE
      WHEN stepped.dt_seconds > ({{MAX_GAP_HOURS}} * 3600.0) THEN 1
      ELSE 0
    END AS gap_after
  FROM (
    SELECT
      src.*,
      EXTRACT(EPOCH FROM (
        LEAD(src.timestamp_utc) OVER (
          PARTITION BY src.equipment_id ORDER BY src.timestamp_utc
        ) - src.timestamp_utc
      )) AS dt_seconds
    FROM base src
  ) stepped
),
lagged AS (
  SELECT
    *,
    CASE
      WHEN raw_fault = LAG(raw_fault) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc)
       AND COALESCE(LAG(gap_after) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc), 0) = 0
      THEN 0 ELSE 1
    END AS is_new_streak
  FROM elapsed_hold
),
grp AS (
  SELECT
    *,
    SUM(is_new_streak)
      OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS UNBOUNDED PRECEDING) AS streak_id
  FROM lagged
),
ranked AS (
  SELECT
    *,
    SUM(held_seconds) OVER (
      PARTITION BY equipment_id, streak_id ORDER BY timestamp_utc
      ROWS UNBOUNDED PRECEDING
    ) AS streak_elapsed
  FROM grp
),
final AS (
  SELECT
    equipment_id,
    held_seconds,
    CASE WHEN raw_fault = 1 AND streak_elapsed >= {{CONFIRM_SECONDS}} THEN 1 ELSE 0 END AS confirmed
  FROM ranked
)
SELECT
  equipment_id,
  SUM(CASE WHEN confirmed = 1 THEN held_seconds ELSE 0.0 END) / 3600.0 AS fault_hours,
  SUM(held_seconds) / 3600.0 AS covered_hours,
  100.0 * SUM(CASE WHEN confirmed = 1 THEN held_seconds ELSE 0.0 END) / NULLIF(SUM(held_seconds), 0.0) AS fault_pct
FROM final
GROUP BY equipment_id;
```
{% endraw %}

### vlv1_clg_valve_leak.sql

`sql/fdd/postgres/rules/vlv1_clg_valve_leak.sql`

{% raw %}
```sql
-- PostgreSQL adaptation. Render numeric template parameters with render_rule.py.
-- Inputs must be scoped to one tenant/site and cadence; see README.md.
-- vlv1_clg_valve_leak.sql — Cooling valve leakage
WITH h AS (
  SELECT
    equipment_id,
    timestamp_utc,
    sat, sat_sp, mat,
    CASE WHEN clg_valve_pct IS NULL THEN NULL WHEN clg_valve_pct > 1.0 THEN clg_valve_pct / 100.0 ELSE clg_valve_pct END AS clg,
    fan_cmd,
    fan_status,
    CASE
      WHEN fan_status IS NOT NULL THEN CASE WHEN fan_status > 0.05 THEN 1 ELSE 0 END
      WHEN fan_cmd IS NOT NULL THEN CASE WHEN (CASE WHEN fan_cmd > 1.0 THEN fan_cmd / 100.0 ELSE fan_cmd END) > 0.01 THEN 1 ELSE 0 END
      ELSE 1
    END AS fan_on

  FROM history
),
base AS (
  SELECT
    equipment_id,
    timestamp_utc,
    CAST(CASE
      WHEN COALESCE(fan_on, 1) = 0 THEN 0
      WHEN clg IS NULL OR sat IS NULL THEN 0
      WHEN clg <= 0.05 AND (
        (sat_sp IS NOT NULL AND sat < sat_sp - {{SAT_ERR}})
        OR (mat IS NOT NULL AND sat < mat - {{MAT_LEAK_DELTA}})
      ) THEN 1
      ELSE 0
    END AS INT) AS raw_fault
  FROM h
),
elapsed_hold AS (
  -- Forward sample-and-hold. A gap longer than MAX_GAP_HOURS is unknown:
  -- it is not fault time, not covered time, and it breaks confirmation.
  -- The last sample has no forward interval.
  SELECT
    stepped.*,
    CASE
      WHEN stepped.dt_seconds IS NULL
        OR stepped.dt_seconds <= 0.0
        OR stepped.dt_seconds > ({{MAX_GAP_HOURS}} * 3600.0)
      THEN 0.0
      ELSE stepped.dt_seconds
    END AS held_seconds,
    CASE
      WHEN stepped.dt_seconds > ({{MAX_GAP_HOURS}} * 3600.0) THEN 1
      ELSE 0
    END AS gap_after
  FROM (
    SELECT
      src.*,
      EXTRACT(EPOCH FROM (
        LEAD(src.timestamp_utc) OVER (
          PARTITION BY src.equipment_id ORDER BY src.timestamp_utc
        ) - src.timestamp_utc
      )) AS dt_seconds
    FROM base src
  ) stepped
),
lagged AS (
  SELECT
    *,
    CASE
      WHEN raw_fault = LAG(raw_fault) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc)
       AND COALESCE(LAG(gap_after) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc), 0) = 0
      THEN 0 ELSE 1
    END AS is_new_streak
  FROM elapsed_hold
),
grp AS (
  SELECT
    *,
    SUM(is_new_streak)
      OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS UNBOUNDED PRECEDING) AS streak_id
  FROM lagged
),
ranked AS (
  SELECT
    *,
    SUM(held_seconds) OVER (
      PARTITION BY equipment_id, streak_id ORDER BY timestamp_utc
      ROWS UNBOUNDED PRECEDING
    ) AS streak_elapsed
  FROM grp
),
final AS (
  SELECT
    equipment_id,
    held_seconds,
    CASE WHEN raw_fault = 1 AND streak_elapsed >= {{CONFIRM_SECONDS}} THEN 1 ELSE 0 END AS confirmed
  FROM ranked
)
SELECT
  equipment_id,
  SUM(CASE WHEN confirmed = 1 THEN held_seconds ELSE 0.0 END) / 3600.0 AS fault_hours,
  SUM(held_seconds) / 3600.0 AS covered_hours,
  100.0 * SUM(CASE WHEN confirmed = 1 THEN held_seconds ELSE 0.0 END) / NULLIF(SUM(held_seconds), 0.0) AS fault_pct
FROM final
GROUP BY equipment_id;
```
{% endraw %}

### wx1_oa_spike.sql

`sql/fdd/postgres/rules/wx1_oa_spike.sql`

{% raw %}
```sql
-- PostgreSQL adaptation. Render numeric template parameters with render_rule.py.
-- Inputs must be scoped to one tenant/site and cadence; see README.md.
-- wx1_oa_spike.sql — OA temperature spike
WITH h AS (
  SELECT
    equipment_id,
    timestamp_utc,
    oa_t,
    LAG(oa_t) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc) AS prev_oa_t
  FROM history
),
base AS (
  SELECT
    equipment_id,
    timestamp_utc,
    CAST(CASE
      WHEN oa_t IS NULL OR prev_oa_t IS NULL THEN 0
      WHEN ABS(oa_t - prev_oa_t) > {{SPIKE_LIMIT}} THEN 1
      ELSE 0
    END AS INT) AS raw_fault
  FROM h
),
elapsed_hold AS (
  -- Forward sample-and-hold. A gap longer than MAX_GAP_HOURS is unknown:
  -- it is not fault time, not covered time, and it breaks confirmation.
  -- The last sample has no forward interval.
  SELECT
    stepped.*,
    CASE
      WHEN stepped.dt_seconds IS NULL
        OR stepped.dt_seconds <= 0.0
        OR stepped.dt_seconds > ({{MAX_GAP_HOURS}} * 3600.0)
      THEN 0.0
      ELSE stepped.dt_seconds
    END AS held_seconds,
    CASE
      WHEN stepped.dt_seconds > ({{MAX_GAP_HOURS}} * 3600.0) THEN 1
      ELSE 0
    END AS gap_after
  FROM (
    SELECT
      src.*,
      EXTRACT(EPOCH FROM (
        LEAD(src.timestamp_utc) OVER (
          PARTITION BY src.equipment_id ORDER BY src.timestamp_utc
        ) - src.timestamp_utc
      )) AS dt_seconds
    FROM base src
  ) stepped
),
lagged AS (
  SELECT
    *,
    CASE
      WHEN raw_fault = LAG(raw_fault) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc)
       AND COALESCE(LAG(gap_after) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc), 0) = 0
      THEN 0 ELSE 1
    END AS is_new_streak
  FROM elapsed_hold
),
grp AS (
  SELECT
    *,
    SUM(is_new_streak)
      OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS UNBOUNDED PRECEDING) AS streak_id
  FROM lagged
),
ranked AS (
  SELECT
    *,
    SUM(held_seconds) OVER (
      PARTITION BY equipment_id, streak_id ORDER BY timestamp_utc
      ROWS UNBOUNDED PRECEDING
    ) AS streak_elapsed
  FROM grp
),
final AS (
  SELECT
    equipment_id,
    held_seconds,
    CASE WHEN raw_fault = 1 AND streak_elapsed >= {{CONFIRM_SECONDS}} THEN 1 ELSE 0 END AS confirmed
  FROM ranked
)
SELECT
  equipment_id,
  SUM(CASE WHEN confirmed = 1 THEN held_seconds ELSE 0.0 END) / 3600.0 AS fault_hours,
  SUM(held_seconds) / 3600.0 AS covered_hours,
  100.0 * SUM(CASE WHEN confirmed = 1 THEN held_seconds ELSE 0.0 END) / NULLIF(SUM(held_seconds), 0.0) AS fault_pct
FROM final
GROUP BY equipment_id;
```
{% endraw %}

### zone_comfort_pct.sql

`sql/fdd/postgres/rules/zone_comfort_pct.sql`

{% raw %}
```sql
-- PostgreSQL adaptation. Render numeric template parameters with render_rule.py.
-- Inputs must be scoped to one tenant/site and cadence; see README.md.
-- zone_comfort_pct.sql
-- Comfort is the share of eligible elapsed time inside the band, not a row count.
WITH ordered AS (
  SELECT
    equipment_id,
    zone_t,
    EXTRACT(EPOCH FROM (
      LEAD(timestamp_utc) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc)
      - timestamp_utc
    )) AS dt_seconds
  FROM history
  WHERE zone_t IS NOT NULL
),
held AS (
  SELECT
    equipment_id,
    zone_t,
    CASE
      WHEN dt_seconds IS NULL OR dt_seconds <= 0.0 OR dt_seconds > ({{MAX_GAP_HOURS}} * 3600.0)
      THEN 0.0
      ELSE dt_seconds
    END AS held_seconds
  FROM ordered
)
SELECT
  equipment_id,
  100.0 * SUM(CASE
    WHEN zone_t >= {{ZONE_T_LO}} AND zone_t <= {{ZONE_T_HI}} THEN held_seconds
    ELSE 0.0
  END) / NULLIF(SUM(held_seconds), 0.0) AS comfort_pct
FROM held
GROUP BY equipment_id;
```
{% endraw %}

### postgres_helpers.sql

`sql/fdd/postgres/postgres_helpers.sql`

{% raw %}
```sql
-- Install once on PostgreSQL in a schema controlled by the application owner.
CREATE SCHEMA IF NOT EXISTS fdd;
CREATE OR REPLACE FUNCTION fdd.try_double(value text)
RETURNS double precision
LANGUAGE plpgsql IMMUTABLE STRICT PARALLEL SAFE
AS $$
BEGIN
  RETURN trim(value)::double precision;
EXCEPTION
  WHEN invalid_text_representation OR numeric_value_out_of_range THEN RETURN NULL;
END;
$$;

-- Sensor sweep assessability (twin of fdd_core::sensor_sweep / pandas sensor_sweep_catalog).
CREATE OR REPLACE FUNCTION fdd.norm_unit(value text)
RETURNS text
LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$
  SELECT lower(regexp_replace(coalesce(btrim(value), ''), '[^a-zA-Z0-9]', '', 'g'));
$$;

CREATE OR REPLACE FUNCTION fdd.quantity_for_sql_role(role text)
RETURNS text
LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$
  SELECT CASE btrim(role)
    WHEN 'oa_t' THEN 'absolute_temperature'
    WHEN 'rat' THEN 'absolute_temperature'
    WHEN 'zone_t' THEN 'absolute_temperature'
    WHEN 'mat' THEN 'absolute_temperature'
    WHEN 'sat' THEN 'absolute_temperature'
    WHEN 'chw_supply_t' THEN 'absolute_temperature'
    WHEN 'chw_return_t' THEN 'absolute_temperature'
    WHEN 'hw_supply_t' THEN 'absolute_temperature'
    WHEN 'hw_return_t' THEN 'absolute_temperature'
    WHEN 'oa_h' THEN 'relative_humidity'
    WHEN 'ra_h' THEN 'relative_humidity'
    WHEN 'zone_rh' THEN 'relative_humidity'
    WHEN 'zone_h' THEN 'relative_humidity'
    WHEN 'ma_h' THEN 'relative_humidity'
    WHEN 'sa_h' THEN 'relative_humidity'
    WHEN 'duct_static' THEN 'air_pressure'
    ELSE NULL
  END;
$$;

CREATE OR REPLACE FUNCTION fdd.unit_declares_quantity(unit text, quantity text)
RETURNS boolean
LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$
  SELECT CASE
    WHEN unit IS NULL OR btrim(unit) = '' THEN false
    WHEN quantity = 'absolute_temperature' THEN
      fdd.norm_unit(unit) IN ('f', 'degf', 'fahrenheit', 'c', 'degc', 'celsius')
    WHEN quantity = 'relative_humidity' THEN
      fdd.norm_unit(unit) IN ('pct', 'percent', 'rh', 'percentrelativehumidity')
      OR position('%' IN unit) > 0
    WHEN quantity = 'air_pressure' THEN
      fdd.norm_unit(unit) IN ('inwc', 'inh2o', 'inw.c.', 'pa', 'pascal')
      OR position('w.c' IN lower(unit)) > 0
    ELSE false
  END;
$$;

CREATE OR REPLACE FUNCTION fdd.is_expected_constant_sql_role(role text)
RETURNS boolean
LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$
  SELECT CASE
    WHEN btrim(role) = '' THEN false
    WHEN fdd.norm_unit(role) LIKE '%sp' THEN true
    WHEN position('setpoint' IN fdd.norm_unit(role)) > 0 THEN true
    WHEN position('status' IN fdd.norm_unit(role)) > 0 THEN true
    WHEN fdd.norm_unit(role) LIKE '%cmd' THEN true
    WHEN position('command' IN fdd.norm_unit(role)) > 0 THEN true
    WHEN fdd.norm_unit(role) = 'occmode' THEN true
    WHEN position('occupied' IN fdd.norm_unit(role)) > 0 THEN true
    WHEN position('occupancy' IN fdd.norm_unit(role)) > 0 THEN true
    WHEN fdd.norm_unit(role) = 'loopenabled' THEN true
    ELSE false
  END;
$$;

CREATE OR REPLACE FUNCTION fdd.sweep_assessable_sql_role(role text, unit text)
RETURNS boolean
LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$
  SELECT CASE
    WHEN fdd.is_expected_constant_sql_role(role) THEN false
    ELSE fdd.unit_declares_quantity(unit, fdd.quantity_for_sql_role(role))
  END;
$$;

CREATE OR REPLACE FUNCTION fdd.mask_sweep_val(role text, unit text, val double precision)
RETURNS double precision
LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$
  SELECT CASE WHEN fdd.sweep_assessable_sql_role(role, unit) THEN val ELSE NULL END;
$$;
```
{% endraw %}

<!-- shipped-sql:end -->
