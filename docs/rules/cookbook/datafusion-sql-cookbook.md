---
title: DataFusion SQL cookbook
parent: Rule Cookbook
nav_order: 1
---

# DataFusion SQL FDD Cookbook

Open-FDD edge executes fault detection as **DataFusion SQL** against Apache Arrow historian tables. Copy-paste rules into the **SQL FDD Rules** tab or `POST /api/fdd-rules/{id}/test-sql`.

**Analyst mirror:** every section below has a matching implementation in the [Pandas cookbook](pandas-cookbook.html) for workflows **outside** Open-FDD.

---

## Table of contents

1. [Platform concepts](#platform-concepts)
2. [Fault confirmation delay (default 5 minutes)](#fault-confirmation-delay-default-5-minutes)
3. [Haystack → SQL columns](#haystack--sql-columns)
4. [Test & activate workflow](#test--activate-workflow)
5. [Sensor validation](#sensor-validation)
6. [Air handling units (FC1–FC15 / GL36 A–M)](#air-handling-units)
7. [VAV zones](#vav-zones)
8. [Economizer & ventilation](#economizer--ventilation)
9. [Central plants](#central-plants)
10. [Heat pumps](#heat-pumps)
11. [Weather station](#weather-station)
12. [Trim & respond advisory (GL36)](#trim--respond-advisory-gl36)
13. [Extended rule families (v2)](#extended-rule-families-v2)
14. [Framework & parity docs](#framework--parity-docs)
15. [Debugging & windowing](#debugging--windowing)

---

## Platform concepts

| Term | Meaning |
|------|---------|
| `telemetry_pivot` | Wide historian table: `timestamp`, `equipment_id`, FDD input columns (`oa_t`, `sat`, …) |
| `telemetry` | Long format (optional) — use pivot for most HVAC rules |
| `fault_raw` | Boolean — instantaneous fault condition (**required** output column) |
| `confirmation_seconds` | Minimum duration fault must hold before latching (API applies **after** SQL) |

Column names come from your **Haystack assignment graph**, not BACnet instance numbers.

### Rule template

```sql
-- confirmation_seconds: 300  (adjust in API/UI — default 5 minutes)
-- param: example_threshold = 5.0

SELECT
  timestamp,
  equipment_id,
  oa_t,
  CASE
    WHEN oa_t IS NULL THEN false
    WHEN oa_t < 40.0 OR oa_t > 110.0 THEN true
    ELSE false
  END AS fault_raw
FROM telemetry_pivot
WHERE equipment_id = 'equip:your-ahu-id'
```

{: .important }
Always handle **`NULL`** — missing samples must not latch faults.

### Command scaling (0–1 vs 0–100 %)

Normalize in assignments, or inline:

```sql
CASE WHEN fan_cmd > 1.0 THEN fan_cmd / 100.0 ELSE fan_cmd END AS fan_norm
```

---

## Fault confirmation delay (default 5 minutes)

Raw rules can flicker true for one poll cycle. Open-FDD debounces **after** SQL returns `fault_raw`.

**Default:** `confirmation_seconds: 300` (5 minutes). Change per rule in the workbench or API:

```json
{"confirmation_seconds": 300}
```

```bash
curl -s -X POST http://127.0.0.1:8080/api/fdd-rules/RULE_ID/test-sql \
  -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"sql":"SELECT timestamp, equipment_id, ... AS fault_raw FROM telemetry_pivot","confirmation_seconds":300}'
```

| Poll interval | `confirmation_seconds` | Approx. consecutive samples |
|---------------|------------------------|----------------------------|
| 60 s | **300** (default) | ~5 |
| 60 s | 600 | ~10 |
| 300 s | 900 | ~3 |

Every rule below includes `-- confirmation_seconds: 300` in comments. Increase for advisory or hunting rules (e.g. FC4 PID hunting often uses **3600**).

---

## Haystack → SQL columns

Binding chain:

```
Driver point → Haystack point → FDD input → telemetry_pivot column
```

1. Commission drivers (BACnet / Modbus / Haystack / JSON)
2. Build Haystack model (equipment + points)
3. **Assignments** — map FDD inputs ([guide]({{ site.baseurl }}/modeling/assignments.html))
4. Pivot exposes FDD input IDs as columns (`oa_t`, `sat`, `zone_t`, …)

Discover columns: SQL FDD schema picker, Plots tab, or `GET /api/fdd-schema/fdd-inputs`.

| Haystack role | FDD input | Pivot column |
|---------------|-----------|--------------|
| OA temp sensor | `oa_t` | `oa_t` |
| SAT sensor | `sat` | `sat` |
| SAT setpoint | `sat_sp` | `sat_sp` |
| Zone temp | `zone_t` | `zone_t` |

Replace `equip:your-ahu-id` with your scoped equipment ref in production.

---

## Test & activate workflow

1. Save rule: `POST /api/fdd-rules` with `review_status: draft`
2. Test: `POST /api/fdd-rules/{id}/test-sql` with **`confirmation_seconds: 300`**
3. Integrator approves in UI
4. Activate: `POST /api/fdd-rules/{id}/activate`

Link rules in **FDD Wires**: `driver_point → model_point → fdd_input → sql_rule → confirmation → fault_output`.

Builder API for simple thresholds:

```bash
curl -s -X POST http://127.0.0.1:8080/api/fdd-rules/builder-sql \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"input":"oa_t","operator":"range","low":40,"high":110,"equipment_id":"equip:validation"}' | jq '.sql'
```

---

## Sensor validation

Data-quality faults (bounds, flatline, rate-of-change, mixing envelope). Gate with equipment state (fan on, occupied) where appropriate.

### Default bounds

Tune per site in SQL literals or assignment transforms.

| Sensor kind | Min | Max | Flatline tol | Max Δ/hr | Code |
|-------------|-----|-----|--------------|----------|------|
| Zone temp (°F) | 55 | 90 | 0.10 | 4.0 | VAV-C |
| Supply air temp | 50 | 110 | 0.15 | 8.0 | AHU-C |
| Return air temp | 55 | 95 | 0.10 | 3.0 | AHU-D |
| Mixed air temp | 40 | 110 | 0.15 | 6.0 | AHU-D |
| Outdoor air temp | −40 | 130 | 0.10 | 12.0 | BLD-B |
| Duct static (inH₂O) | −0.5 | 3.0 | 0.02 | 0.5 | AHU-A |
| Relative humidity (%) | 0 | 100 | 1.0 | 15.0 | DC-C |
| CHW temp | 40 | 90 | 0.10 | 4.0 | CH-D |
| Hot water temp | 70 | 200 | 0.15 | 6.0 | CH-D |
| CO₂ (ppm, occupied) | 400 | 1000 | 5.0 | 200 | VAV-B |

### SV-1 — Zone temperature out of range

**Code:** `VAV-C` · **confirmation_seconds:** 300

```sql
SELECT timestamp, equipment_id, zone_t,
  CASE
    WHEN zone_t IS NULL THEN false
    WHEN zone_t < 55.0 OR zone_t > 90.0 THEN true
    ELSE false
  END AS fault_raw
FROM telemetry_pivot
WHERE equipment_id = 'equip:your-vav'
  AND occ_mode = 'occupied'
```

### SV-2 — OA temperature out of range

**Code:** `BLD-B` · **confirmation_seconds:** 300

```sql
SELECT timestamp, equipment_id, oa_t,
  CASE
    WHEN oa_t IS NULL THEN false
    WHEN oa_t < 40.0 OR oa_t > 110.0 THEN true
    ELSE false
  END AS fault_raw
FROM telemetry_pivot
WHERE equipment_id = 'equip:your-ahu'
```

### SV-3 — OA humidity out of range

**Code:** `DC-C` · **confirmation_seconds:** 300

```sql
SELECT timestamp, equipment_id, oa_h,
  CASE
    WHEN oa_h IS NULL THEN false
    WHEN oa_h < 10.0 OR oa_h > 95.0 THEN true
    ELSE false
  END AS fault_raw
FROM telemetry_pivot
WHERE equipment_id = 'equip:your-ahu'
```

### SV-4 — Mixing envelope (prefer over RAT-only)

When OAT, RAT, and MAT are present, use envelope checks — see [FC2](#fc2--mat-below-oatr-envelope-gl36-rule-b) and [FC3](#fc3--mat-above-oatr-envelope-gl36-rule-c).

### SV-5 — Stale data (no recent samples)

**Code:** `BLD-D` · **confirmation_seconds:** 300

```sql
SELECT equipment_id,
  MAX(timestamp) AS last_ts,
  true AS fault_raw
FROM telemetry_pivot
GROUP BY equipment_id
HAVING MAX(timestamp) < NOW() - INTERVAL '30' MINUTE
```

Adapt interval syntax to your DataFusion version; test in `/sql-fdd` before activate.

### SV-6 — Flatline & rate-of-change

Rolling flatline/spike detection is limited in edge SQL. Use **confirmation_seconds** with bounds rules, or run full rolling logic in the [Pandas cookbook](pandas-cookbook.html#sensor-validation).

---

## Air handling units

Reference: Open-FDD AHU fault conditions **FC1–FC15** (GL36-inspired). Default **`confirmation_seconds: 300`** unless noted.

Shared params (tune per site):

| Param | Default | Used in |
|-------|---------|---------|
| `mix_tol` | 1.15 °F | FC2, FC3, FC5, FC8, FC12 |
| `supply_tol` | 1.15 °F | FC5, FC8, FC12, FC13 |
| `ahu_min_oa_dpr` | 0.0–1.0 | FC4, FC6, FC8–FC15 |
| `delta_supply_fan` | 0.55 °F | FC5, FC8, FC12, FC14, FC15 |
| `fan_on_min` | 0.01 | Most FC rules |

---

### FC1 — Duct static below SP at full fan (GL36 Rule A)

**Code:** `AHU-A` · **confirmation_seconds:** 300 · **param:** `duct_static_err=0.12`, `fan_hi=0.87`

```sql
SELECT timestamp, equipment_id, duct_static, duct_static_sp, fan_cmd,
  CASE
    WHEN duct_static IS NULL OR duct_static_sp IS NULL OR fan_cmd IS NULL THEN false
    WHEN duct_static < duct_static_sp - 0.12
     AND CASE WHEN fan_cmd > 1.0 THEN fan_cmd/100.0 ELSE fan_cmd END >= 0.87 THEN true
    ELSE false
  END AS fault_raw
FROM telemetry_pivot
WHERE equipment_id = 'equip:your-ahu'
```

---

### FC2 — MAT below OAT/RAT envelope (GL36 Rule B)

**Code:** `AHU-D` · **confirmation_seconds:** 600 · **param:** `mix_tol=1.15`

```sql
SELECT timestamp, equipment_id, mat, oat, rat, fan_cmd,
  CASE
    WHEN mat IS NULL OR oat IS NULL OR rat IS NULL OR fan_cmd IS NULL THEN false
    WHEN CASE WHEN fan_cmd > 1.0 THEN fan_cmd/100.0 ELSE fan_cmd END <= 0.01 THEN false
    WHEN mat - 1.15 < LEAST(rat - 1.15, oat - 1.15) THEN true
    ELSE false
  END AS fault_raw
FROM telemetry_pivot
WHERE equipment_id = 'equip:your-ahu'
```

---

### FC3 — MAT above OAT/RAT envelope (GL36 Rule C)

**Code:** `AHU-D` · **confirmation_seconds:** 600

```sql
SELECT timestamp, equipment_id, mat, oat, rat, fan_cmd,
  CASE
    WHEN mat IS NULL OR oat IS NULL OR rat IS NULL OR fan_cmd IS NULL THEN false
    WHEN CASE WHEN fan_cmd > 1.0 THEN fan_cmd/100.0 ELSE fan_cmd END <= 0.01 THEN false
    WHEN mat - 1.15 > GREATEST(rat + 1.15, oat + 1.15) THEN true
    ELSE false
  END AS fault_raw
FROM telemetry_pivot
WHERE equipment_id = 'equip:your-ahu'
```

---

### FC4 — PID hunting (operating-state oscillation)

**Code:** `AHU-PID-HUNT` · **confirmation_seconds:** 3600 (recommended) · **param:** `delta_os_max=5`

Counts excessive **operating-mode transitions per hour** (heating-only, economizer-only, economizer+mech, mech-only). High transition count indicates PID loops hunting.

**Edge SQL** — hourly mode-transition count via window (simplified; full resample logic in [Pandas FC4](pandas-cookbook.html#fc4--pid-hunting-operating-state-oscillation)):

```sql
-- confirmation_seconds: 3600
-- param: delta_os_max = 5, ahu_min_oa_dpr = 0.05

WITH base AS (
  SELECT
    timestamp,
    equipment_id,
    CASE
      WHEN htg_valve_pct > 0 AND clg_valve_pct = 0
       AND CASE WHEN fan_cmd > 1.0 THEN fan_cmd/100.0 ELSE fan_cmd END > 0
       AND oa_damper_pct = 0.05 THEN 'htg'
      WHEN htg_valve_pct = 0 AND clg_valve_pct = 0
       AND CASE WHEN fan_cmd > 1.0 THEN fan_cmd/100.0 ELSE fan_cmd END > 0
       AND oa_damper_pct > 0.05 THEN 'econ'
      WHEN htg_valve_pct = 0 AND clg_valve_pct > 0
       AND CASE WHEN fan_cmd > 1.0 THEN fan_cmd/100.0 ELSE fan_cmd END > 0
       AND oa_damper_pct > 0.05 THEN 'econ_mech'
      WHEN htg_valve_pct = 0 AND clg_valve_pct > 0
       AND CASE WHEN fan_cmd > 1.0 THEN fan_cmd/100.0 ELSE fan_cmd END > 0
       AND oa_damper_pct = 0.05 THEN 'mech'
      ELSE 'other'
    END AS os_mode
  FROM telemetry_pivot
  WHERE equipment_id = 'equip:your-ahu'
),
transitions AS (
  SELECT *,
    CASE WHEN os_mode <> LAG(os_mode) OVER (ORDER BY timestamp)
          AND LAG(os_mode) OVER (ORDER BY timestamp) IS NOT NULL
         THEN 1 ELSE 0 END AS mode_change
  FROM base
)
SELECT timestamp, equipment_id,
  CASE
    WHEN SUM(mode_change) OVER (
      ORDER BY timestamp
      RANGE BETWEEN INTERVAL '1' HOUR PRECEDING AND CURRENT ROW
    ) > 5 THEN true
    ELSE false
  END AS fault_raw
FROM transitions
```

Replace `0.05` with your site's `ahu_min_oa_dpr`. Test window syntax in `/sql-fdd` — DataFusion versions differ on `RANGE` intervals.

---

### FC5 — SAT cold when heating commanded (GL36 Rule D)

**Code:** `AHU-B` · **confirmation_seconds:** 600 · **param:** `delta_supply_fan=0.55`

```sql
SELECT timestamp, equipment_id, sat, mat, htg_valve_pct, fan_cmd,
  CASE
    WHEN sat IS NULL OR mat IS NULL OR htg_valve_pct IS NULL OR fan_cmd IS NULL THEN false
    WHEN CASE WHEN fan_cmd > 1.0 THEN fan_cmd/100.0 ELSE fan_cmd END <= 0.01 THEN false
    WHEN CASE WHEN htg_valve_pct > 1.0 THEN htg_valve_pct/100.0 ELSE htg_valve_pct END <= 0.01 THEN false
    WHEN sat + 1.15 <= mat - 1.15 + 0.55 THEN true
    ELSE false
  END AS fault_raw
FROM telemetry_pivot
WHERE equipment_id = 'equip:your-ahu'
```

---

### FC6 — Estimated OA fraction mismatch

**Code:** `AHU-OA-FRAC` · **confirmation_seconds:** 600 · **param:** `airflow_err=0.15`, `oat_rat_delta_min=5.0`

Requires `vav_total_flow` historian column (summed VAV airflow or fan AFMS).

```sql
SELECT timestamp, equipment_id, mat, oat, rat, vav_total_flow,
  htg_valve_pct, clg_valve_pct, oa_damper_pct, fan_cmd,
  CASE
    WHEN mat IS NULL OR oat IS NULL OR rat IS NULL OR vav_total_flow IS NULL THEN false
    WHEN ABS(rat - oat) < 5.0 THEN false
    WHEN ABS(oat - rat) < 0.01 THEN false
    WHEN (
      ABS(
        GREATEST((mat - rat) / NULLIF(oat - rat, 0), 0)
        - (ahu_min_cfm_design / NULLIF(vav_total_flow, 0))
      ) > 0.15
      AND ABS(rat - oat) >= 5.0
      AND (
        (CASE WHEN htg_valve_pct > 1.0 THEN htg_valve_pct/100.0 ELSE htg_valve_pct END > 0
         AND CASE WHEN fan_cmd > 1.0 THEN fan_cmd/100.0 ELSE fan_cmd END > 0)
        OR
        (CASE WHEN htg_valve_pct > 1.0 THEN htg_valve_pct/100.0 ELSE htg_valve_pct END = 0
         AND CASE WHEN clg_valve_pct > 1.0 THEN clg_valve_pct/100.0 ELSE clg_valve_pct END > 0
         AND oa_damper_pct = 0.05)
      )
    ) THEN true
    ELSE false
  END AS fault_raw
FROM telemetry_pivot
WHERE equipment_id = 'equip:your-ahu'
```

Tune `ahu_min_cfm_design` and `0.05` (`ahu_min_oa_dpr`) per site.

---

### FC7 — SAT low with full heating (GL36 Rule E)

**Code:** `AHU-C` · **confirmation_seconds:** 600 · **param:** `sat_err=1.0`

```sql
SELECT timestamp, equipment_id, sat, sat_sp, htg_valve_pct, fan_cmd,
  CASE
    WHEN sat IS NULL OR sat_sp IS NULL OR htg_valve_pct IS NULL OR fan_cmd IS NULL THEN false
    WHEN CASE WHEN fan_cmd > 1.0 THEN fan_cmd/100.0 ELSE fan_cmd END <= 0.01 THEN false
    WHEN sat < sat_sp - 1.0
     AND CASE WHEN htg_valve_pct > 1.0 THEN htg_valve_pct/100.0 ELSE htg_valve_pct END > 0.9 THEN true
    ELSE false
  END AS fault_raw
FROM telemetry_pivot
WHERE equipment_id = 'equip:your-ahu'
```

---

### FC8 — SAT above blend in economizer mode (GL36 Rule F)

**Code:** `AHU-E` · **confirmation_seconds:** 600 · **param:** `ahu_min_oa_dpr=0.05`

```sql
SELECT timestamp, equipment_id, sat, mat, oa_damper_pct, clg_valve_pct,
  CASE
    WHEN sat IS NULL OR mat IS NULL OR oa_damper_pct IS NULL OR clg_valve_pct IS NULL THEN false
    WHEN oa_damper_pct <= 0.05 OR clg_valve_pct >= 0.1 THEN false
    WHEN ABS(sat - 0.55 - mat) > SQRT(POWER(1.15, 2) + POWER(1.15, 2)) THEN true
    ELSE false
  END AS fault_raw
FROM telemetry_pivot
WHERE equipment_id = 'equip:your-ahu'
```

---

### FC9 — OAT too warm for free cooling (GL36 Rule G)

**Code:** `AHU-E` · **confirmation_seconds:** 600

```sql
SELECT timestamp, equipment_id, oat, sat_sp, oa_damper_pct, clg_valve_pct,
  CASE
    WHEN oat IS NULL OR sat_sp IS NULL OR oa_damper_pct IS NULL OR clg_valve_pct IS NULL THEN false
    WHEN oa_damper_pct <= 0.05 OR clg_valve_pct >= 0.1 THEN false
    WHEN (oat - 1.15) > (sat_sp - 0.55 + 1.15) THEN true
    ELSE false
  END AS fault_raw
FROM telemetry_pivot
WHERE equipment_id = 'equip:your-ahu'
```

---

### FC10 — OAT/MAT mismatch + mech cooling (GL36 Rule H)

**Code:** `AHU-E` · **confirmation_seconds:** 600

```sql
SELECT timestamp, equipment_id, mat, oat, oa_damper_pct, clg_valve_pct,
  CASE
    WHEN mat IS NULL OR oat IS NULL OR oa_damper_pct IS NULL OR clg_valve_pct IS NULL THEN false
    WHEN clg_valve_pct <= 0.01 OR oa_damper_pct <= 0.9 THEN false
    WHEN ABS(mat - oat) > SQRT(POWER(1.15, 2) + POWER(1.15, 2)) THEN true
    ELSE false
  END AS fault_raw
FROM telemetry_pivot
WHERE equipment_id = 'equip:your-ahu'
```

---

### FC11 — OAT/MAT mismatch economizer-only (GL36 Rule I)

**Code:** `AHU-E` · **confirmation_seconds:** 600

```sql
SELECT timestamp, equipment_id, oat, sat_sp, oa_damper_pct, clg_valve_pct,
  CASE
    WHEN oat IS NULL OR sat_sp IS NULL OR oa_damper_pct IS NULL OR clg_valve_pct IS NULL THEN false
    WHEN clg_valve_pct <= 0.01 OR oa_damper_pct <= 0.9 THEN false
    WHEN (oat + 1.15) < (sat_sp - 0.55 - 1.15) THEN true
    ELSE false
  END AS fault_raw
FROM telemetry_pivot
WHERE equipment_id = 'equip:your-ahu'
```

---

### FC12 — SAT above blend in cooling (GL36 Rule J)

**Code:** `AHU-B` · **confirmation_seconds:** 600

```sql
SELECT timestamp, equipment_id, sat, mat, oa_damper_pct, clg_valve_pct,
  CASE
    WHEN sat IS NULL OR mat IS NULL OR oa_damper_pct IS NULL OR clg_valve_pct IS NULL THEN false
    WHEN clg_valve_pct <= 0.01 THEN false
    WHEN (
      (sat - 1.15 - 0.55 > mat + 1.15 AND oa_damper_pct = 0.05)
      OR (sat - 1.15 - 0.55 > mat + 1.15 AND oa_damper_pct > 0.9)
    ) THEN true
    ELSE false
  END AS fault_raw
FROM telemetry_pivot
WHERE equipment_id = 'equip:your-ahu'
```

---

### FC13 — SAT above SP at full cooling (GL36 Rule K)

**Code:** `AHU-C` · **confirmation_seconds:** 600 · **param:** `sat_err=1.0`

```sql
SELECT timestamp, equipment_id, sat, sat_sp, oa_damper_pct, clg_valve_pct,
  CASE
    WHEN sat IS NULL OR sat_sp IS NULL OR oa_damper_pct IS NULL OR clg_valve_pct IS NULL THEN false
    WHEN clg_valve_pct <= 0.01 THEN false
    WHEN sat > sat_sp + 1.0
     AND (oa_damper_pct = 0.05 OR oa_damper_pct > 0.9) THEN true
    ELSE false
  END AS fault_raw
FROM telemetry_pivot
WHERE equipment_id = 'equip:your-ahu'
```

---

### FC14 — CHW coil ΔT when inactive (GL36 Rule L)

**Code:** `CH-C` · **confirmation_seconds:** 600

```sql
SELECT timestamp, equipment_id,
  clg_coil_enter_t, clg_coil_leave_t, oa_damper_pct, htg_valve_pct, clg_valve_pct, fan_cmd,
  CASE
    WHEN clg_coil_enter_t IS NULL OR clg_coil_leave_t IS NULL THEN false
    WHEN (clg_coil_enter_t - clg_coil_leave_t) >= SQRT(POWER(1.15, 2) + POWER(1.15, 2)) + 0.55
     AND (
       (oa_damper_pct > 0.05 AND clg_valve_pct < 0.1)
       OR (htg_valve_pct > 0 AND fan_cmd > 0)
     ) THEN true
    ELSE false
  END AS fault_raw
FROM telemetry_pivot
WHERE equipment_id = 'equip:your-ahu'
```

---

### FC15 — HW coil ΔT when inactive (GL36 Rule M)

**Code:** `AHU-B` · **confirmation_seconds:** 600

```sql
SELECT timestamp, equipment_id,
  htg_coil_enter_t, htg_coil_leave_t, oa_damper_pct, htg_valve_pct, clg_valve_pct, fan_cmd,
  CASE
    WHEN htg_coil_enter_t IS NULL OR htg_coil_leave_t IS NULL THEN false
    WHEN (htg_coil_enter_t - htg_coil_leave_t) >= SQRT(POWER(1.15, 2) + POWER(1.15, 2)) + 0.55
     AND (
       (oa_damper_pct > 0.05 AND clg_valve_pct < 0.1)
       OR (clg_valve_pct > 0.01 AND oa_damper_pct = 0.05)
       OR (clg_valve_pct > 0.01 AND oa_damper_pct > 0.9)
     ) THEN true
    ELSE false
  END AS fault_raw
FROM telemetry_pivot
WHERE equipment_id = 'equip:your-ahu'
```

---

### AHU — Additional patterns

#### SAT deviation from setpoint

**Code:** `SAT_DEVIATION_HIGH` · **confirmation_seconds:** 600 · **param:** `err=5.0`

```sql
SELECT timestamp, equipment_id, sat, sat_sp,
  CASE
    WHEN sat IS NULL OR sat_sp IS NULL THEN false
    WHEN ABS(sat - sat_sp) > 5.0 THEN true
    ELSE false
  END AS fault_raw
FROM telemetry_pivot
WHERE equipment_id = 'equip:your-ahu'
```

#### Duct static pressure high

**Code:** `DUCT_STATIC_HIGH` · **confirmation_seconds:** 300 · **param:** `margin=0.25`

```sql
SELECT timestamp, equipment_id, duct_static, duct_static_sp,
  CASE
    WHEN duct_static IS NULL OR duct_static_sp IS NULL THEN false
    WHEN duct_static > duct_static_sp + 0.25 THEN true
    ELSE false
  END AS fault_raw
FROM telemetry_pivot
WHERE equipment_id = 'equip:your-ahu'
```

#### Heating and cooling simultaneous

**Code:** `HEAT_COOL_SIMULTANEOUS` · **confirmation_seconds:** 300

```sql
SELECT timestamp, equipment_id, htg_valve_pct, clg_valve_pct,
  CASE
    WHEN htg_valve_pct IS NULL OR clg_valve_pct IS NULL THEN false
    WHEN htg_valve_pct > 10.0 AND clg_valve_pct > 10.0 THEN true
    ELSE false
  END AS fault_raw
FROM telemetry_pivot
WHERE equipment_id = 'equip:your-ahu'
```

#### Fan off but duct still warm

**Code:** `FAN_OFF_DUCT_WARM` · **confirmation_seconds:** 600 · **param:** `delta=15.0`

```sql
SELECT timestamp, equipment_id, fan_cmd, duct_t, oa_t,
  CASE
    WHEN fan_cmd IS NULL OR duct_t IS NULL OR oa_t IS NULL THEN false
    WHEN fan_cmd = false AND duct_t > oa_t + 15.0 THEN true
    ELSE false
  END AS fault_raw
FROM telemetry_pivot
WHERE equipment_id = 'equip:your-ahu'
```

---

## VAV zones

### VAV-1 — Zone temperature comfort band

**Code:** `ZONE_TEMP_OUT_OF_BAND` · **confirmation_seconds:** 900 · **param:** `lo=68`, `hi=76`

```sql
SELECT timestamp, equipment_id, zone_t,
  CASE
    WHEN zone_t IS NULL THEN false
    WHEN zone_t < 68.0 OR zone_t > 76.0 THEN true
    ELSE false
  END AS fault_raw
FROM telemetry_pivot
WHERE equipment_id = 'equip:your-vav'
```

### VAV-2 — Night setback miss

**Code:** `NIGHT_SETBACK_MISS` · **confirmation_seconds:** 1800 · **param:** `unocc_max=78`

```sql
SELECT timestamp, equipment_id, zone_t, occ_mode,
  CASE
    WHEN zone_t IS NULL OR occ_mode IS NULL THEN false
    WHEN occ_mode = 'unoccupied' AND zone_t > 78.0 THEN true
    ELSE false
  END AS fault_raw
FROM telemetry_pivot
WHERE equipment_id = 'equip:your-vav'
```

### VAV-3 — Excessive reheat during warm weather

**Code:** `VAV-REHEAT-WARM` · **confirmation_seconds:** 300 · **param:** `oat_cutoff=78`, `reheat_min=0.52`

```sql
SELECT timestamp, equipment_id, oa_t, reheat_valve_pct,
  CASE
    WHEN oa_t IS NULL OR reheat_valve_pct IS NULL THEN false
    WHEN oa_t > 78.0
     AND CASE WHEN reheat_valve_pct > 1.0 THEN reheat_valve_pct/100.0 ELSE reheat_valve_pct END > 0.52 THEN true
    ELSE false
  END AS fault_raw
FROM telemetry_pivot
WHERE equipment_id = 'equip:your-vav'
```

### VAV-4 — Damper stuck at full open

**Code:** `VAV-DPR-100` · **confirmation_seconds:** 900 · **param:** `full_open=97.5`

Use confirmation to approximate sustained full-open (rolling min is easier in [Pandas VAV-4](pandas-cookbook.html#vav-zones)):

```sql
SELECT timestamp, equipment_id, damper_pct,
  CASE
    WHEN damper_pct IS NULL THEN false
    WHEN damper_pct > 97.5 THEN true
    ELSE false
  END AS fault_raw
FROM telemetry_pivot
WHERE equipment_id = 'equip:your-vav'
```

---

## Economizer & ventilation

### ECON-1 — Economizer stuck closed

**Code:** `ECONOMIZER_STUCK_CLOSED` · **confirmation_seconds:** 600

```sql
SELECT timestamp, equipment_id, fan_cmd, oa_damper_pct, oa_t,
  CASE
    WHEN fan_cmd IS NULL OR oa_damper_pct IS NULL OR oa_t IS NULL THEN false
    WHEN fan_cmd = true AND oa_damper_pct < 5.0 AND oa_t > 55.0 THEN true
    ELSE false
  END AS fault_raw
FROM telemetry_pivot
WHERE equipment_id = 'equip:your-ahu'
```

### ECON-2 — Economizing when outdoor unfavorable

**Code:** `ECON-WHEN-SHOULDNT` · **confirmation_seconds:** 300 · **param:** `oat_cutoff=63`, `dpr_min=0.42`

```sql
SELECT timestamp, equipment_id, oa_t, oa_damper_pct,
  CASE
    WHEN oa_t IS NULL OR oa_damper_pct IS NULL THEN false
    WHEN oa_t > 63.0 AND oa_damper_pct > 0.42 THEN true
    ELSE false
  END AS fault_raw
FROM telemetry_pivot
WHERE equipment_id = 'equip:your-ahu'
```

### ECON-3 — Mech cooling when econ available

**Code:** `MECH-WHEN-ECON` · **confirmation_seconds:** 300

```sql
SELECT timestamp, equipment_id, oa_t, oa_damper_pct, clg_valve_pct,
  CASE
    WHEN oa_t IS NULL OR oa_damper_pct IS NULL OR clg_valve_pct IS NULL THEN false
    WHEN oa_t < 63.0 AND oa_damper_pct < 0.32 AND clg_valve_pct > 0.01 THEN true
    ELSE false
  END AS fault_raw
FROM telemetry_pivot
WHERE equipment_id = 'equip:your-ahu'
```

### ECON-4 — Low estimated OA fraction

**Code:** `LOW-OA-FRAC` · **confirmation_seconds:** 600 · **param:** `oa_min_pct=21`

```sql
SELECT timestamp, equipment_id, mat, rat, oat, fan_cmd,
  CASE
    WHEN mat IS NULL OR rat IS NULL OR oat IS NULL OR fan_cmd IS NULL THEN false
    WHEN CASE WHEN fan_cmd > 1.0 THEN fan_cmd/100.0 ELSE fan_cmd END <= 0.01 THEN false
    WHEN ABS(rat - oat) <= 2.2 THEN false
    WHEN ((mat - rat) / NULLIF(oat - rat, 0) * 100.0) < 21.0 THEN true
    ELSE false
  END AS fault_raw
FROM telemetry_pivot
WHERE equipment_id = 'equip:your-ahu'
```

### ECON-5 — Preheat over-conditioning

**Code:** `PREHEAT-WASTE` · **confirmation_seconds:** 600 · **param:** `excess_tol=2.2`

```sql
SELECT timestamp, equipment_id, preheat_leave_t, sat_sp, oa_t, htg_valve_pct,
  CASE
    WHEN preheat_leave_t IS NULL OR sat_sp IS NULL OR oa_t IS NULL OR htg_valve_pct IS NULL THEN false
    WHEN htg_valve_pct <= 0.01 THEN false
    WHEN (
      (oa_t > sat_sp AND preheat_leave_t - oa_t > 2.2)
      OR (oa_t < sat_sp AND preheat_leave_t - sat_sp > 2.2)
    ) THEN true
    ELSE false
  END AS fault_raw
FROM telemetry_pivot
WHERE equipment_id = 'equip:your-ahu'
```

---

## Central plants

### CHW-1 — Low chilled-water delta-T

**Code:** `CHW-DT-001` · **confirmation_seconds:** 900 · **param:** `min_dt=4.0`

```sql
SELECT timestamp, equipment_id, chw_supply_t, chw_return_t, chw_pump_cmd,
  CASE
    WHEN chw_supply_t IS NULL OR chw_return_t IS NULL THEN false
    WHEN chw_pump_cmd IS NULL OR chw_pump_cmd = false THEN false
    WHEN (chw_return_t - chw_supply_t) < 4.0 THEN true
    ELSE false
  END AS fault_raw
FROM telemetry_pivot
WHERE equipment_id = 'equip:your-chiller-plant'
```

### CHW-2 — DP below SP at max pump speed

**Code:** `CHW-DP-001` · **confirmation_seconds:** 300 · **param:** `dp_margin=2.2`, `pmp_hi=0.87`

```sql
SELECT timestamp, equipment_id, chw_dp, chw_dp_sp, chw_pump_cmd,
  CASE
    WHEN chw_dp IS NULL OR chw_dp_sp IS NULL OR chw_pump_cmd IS NULL THEN false
    WHEN chw_dp < chw_dp_sp - 2.2
     AND CASE WHEN chw_pump_cmd > 1.0 THEN chw_pump_cmd/100.0 ELSE chw_pump_cmd END >= 0.87 THEN true
    ELSE false
  END AS fault_raw
FROM telemetry_pivot
WHERE equipment_id = 'equip:your-chiller-plant'
```

### CHW-3 — Plant supply temp outside deadband

**Code:** `CHW-TEMP-DB` · **confirmation_seconds:** 300 · **param:** `sp_band=2.2`

```sql
SELECT timestamp, equipment_id, chw_supply_t, chw_supply_t_sp, chw_pump_cmd,
  CASE
    WHEN chw_supply_t IS NULL OR chw_supply_t_sp IS NULL OR chw_pump_cmd IS NULL THEN false
    WHEN chw_pump_cmd <= 0.01 THEN false
    WHEN chw_supply_t < chw_supply_t_sp - 2.2 OR chw_supply_t > chw_supply_t_sp + 2.2 THEN true
    ELSE false
  END AS fault_raw
FROM telemetry_pivot
WHERE equipment_id = 'equip:your-chiller-plant'
```

### CHW-4 — Flow high at max pump

**Code:** `CHW-FLOW-HIGH` · **confirmation_seconds:** 300 · **param:** `flow_hi=1100`

```sql
SELECT timestamp, equipment_id, chw_flow, chw_pump_cmd,
  CASE
    WHEN chw_flow IS NULL OR chw_pump_cmd IS NULL THEN false
    WHEN chw_flow > 1100.0
     AND CASE WHEN chw_pump_cmd > 1.0 THEN chw_pump_cmd/100.0 ELSE chw_pump_cmd END >= 0.87 THEN true
    ELSE false
  END AS fault_raw
FROM telemetry_pivot
WHERE equipment_id = 'equip:your-chiller-plant'
```

Validate with `POST /api/fdd/inject-scenario` before enabling on live plant points.

---

## Heat pumps

### HP-1 — Discharge cold when heating

**Code:** `HP-D` · **confirmation_seconds:** 600 · **param:** `min_sat=85`, `zone_cold=69`

```sql
SELECT timestamp, equipment_id, sat, zone_t, fan_cmd,
  CASE
    WHEN sat IS NULL OR zone_t IS NULL OR fan_cmd IS NULL THEN false
    WHEN fan_cmd <= 0.01 THEN false
    WHEN zone_t < 69.0 AND sat < 85.0 THEN true
    ELSE false
  END AS fault_raw
FROM telemetry_pivot
WHERE equipment_id = 'equip:your-hp'
```

---

## Weather station

### WX-1 — Temperature spike between readings

**Code:** `WX-SPIKE` · **confirmation_seconds:** 300 · **param:** `spike_limit=16.0`

Edge SQL — compare to previous sample:

```sql
SELECT timestamp, equipment_id, oa_t,
  CASE
    WHEN oa_t IS NULL THEN false
    WHEN ABS(oa_t - LAG(oa_t) OVER (ORDER BY timestamp)) > 16.0 THEN true
    ELSE false
  END AS fault_raw
FROM telemetry_pivot
WHERE equipment_id = 'equip:weather-station'
```

### WX-2 — Gust lower than sustained wind

**Code:** `WX-GUST` · **confirmation_seconds:** 300

```sql
SELECT timestamp, equipment_id, wind_gust, wind_speed,
  CASE
    WHEN wind_gust IS NULL OR wind_speed IS NULL THEN false
    WHEN wind_gust < wind_speed THEN true
    ELSE false
  END AS fault_raw
FROM telemetry_pivot
WHERE equipment_id = 'equip:weather-station'
```

---

## Trim & respond advisory (GL36)

Advisory faults for sequence health — use **`confirmation_seconds: 1800`** or higher.

### TRIM-1 — Duct static trim advisory

**Code:** `AHU-TRIM-ADV`

```sql
SELECT timestamp, equipment_id, duct_static, vav_press_req_sum,
  CASE
    WHEN duct_static IS NULL OR vav_press_req_sum IS NULL THEN false
    WHEN duct_static > 0.80 AND vav_press_req_sum < 1.0 AND duct_static > 1.35 THEN true
    ELSE false
  END AS fault_raw
FROM telemetry_pivot
WHERE equipment_id = 'equip:your-ahu'
```

### TRIM-2 — Chiller plant enable advisory

**Code:** `CHW-ENABLE-ADV`

```sql
SELECT timestamp, equipment_id, chw_valve_req_count,
  CASE
    WHEN chw_valve_req_count IS NULL THEN false
    WHEN chw_valve_req_count < 2 THEN true
    ELSE false
  END AS fault_raw
FROM telemetry_pivot
WHERE equipment_id = 'equip:your-chiller-plant'
```

### TRIM-3 — HWST trim advisory

**Code:** `HW-TRIM-ADV`

```sql
SELECT timestamp, equipment_id, hw_supply_t, hw_reset_req_sum,
  CASE
    WHEN hw_supply_t IS NULL OR hw_reset_req_sum IS NULL THEN false
    WHEN hw_supply_t < 120.0 AND hw_reset_req_sum > 2.0 THEN true
    ELSE false
  END AS fault_raw
FROM telemetry_pivot
WHERE equipment_id = 'equip:your-boiler-plant'
```

### TRIM-4 — CHW plant reset advisory

**Code:** `CHW-RESET-ADV`

```sql
SELECT timestamp, equipment_id, chw_supply_t, chw_reset_req_sum,
  CASE
    WHEN chw_supply_t IS NULL OR chw_reset_req_sum IS NULL THEN false
    WHEN chw_supply_t < 45.0 AND chw_reset_req_sum < 1.0 THEN true
    ELSE false
  END AS fault_raw
FROM telemetry_pivot
WHERE equipment_id = 'equip:your-chiller-plant'
```

---

## Extended rule families (v2)

Standards-first rules from public FDD / re-tuning literature. Each has a matching [Pandas](pandas-cookbook.html#extended-rule-families-v2) section. Metadata follows the [rule schema](rule-schema.html). Use [prerequisite macros](prerequisite-macros.html) inline.

### RESET-1 — SAT reset not tracking outdoor air

| Field | Value |
|-------|-------|
| **taxonomy_path** | `reset.ahu.sat_oa_reset_missing` |
| **severity** | 2 · **confirmation_seconds:** 900 |
| **required_points** | `sat_sp`, `oat`, `fan_status` |
| **prerequisites** | `macro.fan_proven_on`, `macro.reset_enabled` |

**Intent:** Supply air temperature setpoint should reset with outdoor air when reset is enabled (ASHRAE GL36 / AIRCx common finding).

```sql
-- confirmation_seconds: 900
-- param: sat_reset_err_max = 3.0  (site-adjustable °F)
SELECT timestamp, equipment_id, sat_sp, oat, fan_status,
  CASE
    WHEN sat_sp IS NULL OR oat IS NULL OR fan_status IS NULL THEN false
    WHEN fan_status = false THEN false
    WHEN COALESCE(reset_enable, true) = false THEN false
    WHEN ABS(sat_sp - (52.0 + 0.25 * (oat - 65.0))) > 3.0 THEN true
    ELSE false
  END AS fault_raw
FROM telemetry_pivot
WHERE equipment_id = 'equip:your-ahu'
```

**Validation:** normal cooling day → false; fixed SAT SP on hot day → true; missing `sat_sp` → false.

---

### SCHED-1 — Equipment running while unoccupied

| Field | Value |
|-------|-------|
| **taxonomy_path** | `schedule.ahu.unoccupied_runtime` |
| **severity** | 2 · **confirmation_seconds:** 1800 |
| **required_points** | `fan_status`, `occ_mode` |

```sql
-- confirmation_seconds: 1800
SELECT timestamp, equipment_id, fan_status, occ_mode,
  CASE
    WHEN fan_status IS NULL OR occ_mode IS NULL THEN false
    WHEN occ_mode = 'unoccupied' AND fan_status = true THEN true
    ELSE false
  END AS fault_raw
FROM telemetry_pivot
WHERE equipment_id = 'equip:your-ahu'
```

---

### OVR-1 — Persistent manual override

| Field | Value |
|-------|-------|
| **taxonomy_path** | `override.ahu.persistent_manual` |
| **severity** | 2 · **confirmation_seconds:** 3600 |
| **required_points** | `override_active` |

```sql
-- confirmation_seconds: 3600
SELECT timestamp, equipment_id, override_active,
  CASE
    WHEN override_active IS NULL THEN false
    WHEN override_active = true THEN true
    ELSE false
  END AS fault_raw
FROM telemetry_pivot
WHERE equipment_id = 'equip:your-ahu'
```

---

### CMD-1 — Fan command vs status mismatch

| Field | Value |
|-------|-------|
| **taxonomy_path** | `command.status.ahu.fan_cmd_status` |
| **severity** | 3 · **confirmation_seconds:** 600 |
| **required_points** | `fan_cmd`, `fan_status` |

```sql
-- confirmation_seconds: 600
SELECT timestamp, equipment_id, fan_cmd, fan_status,
  CASE
    WHEN fan_cmd IS NULL OR fan_status IS NULL THEN false
    WHEN (CASE WHEN fan_cmd > 1.0 THEN fan_cmd/100.0 ELSE fan_cmd END >= 0.05)
     <> fan_status THEN true
    ELSE false
  END AS fault_raw
FROM telemetry_pivot
WHERE equipment_id = 'equip:your-ahu'
```

---

### OA-1 — Low estimated outdoor air fraction

| Field | Value |
|-------|-------|
| **taxonomy_path** | `ventilation.ahu.low_oa_fraction` |
| **severity** | 2 · **confirmation_seconds:** 900 |
| **required_points** | `oa_t`, `ra_t`, `mat`, `fan_status` |

```sql
-- confirmation_seconds: 900
-- param: min_oa_frac = 0.15
SELECT timestamp, equipment_id, oa_t, ra_t, mat, fan_status,
  CASE
    WHEN oa_t IS NULL OR ra_t IS NULL OR mat IS NULL OR fan_status IS NULL THEN false
    WHEN fan_status = false THEN false
    WHEN ABS(ra_t - oa_t) < 0.5 THEN false
    WHEN ((mat - ra_t) / NULLIF(oa_t - ra_t, 0)) < 0.15 THEN true
    ELSE false
  END AS fault_raw
FROM telemetry_pivot
WHERE equipment_id = 'equip:your-ahu'
```

---

### VLV-1 — Cooling valve leakage

| Field | Value |
|-------|-------|
| **taxonomy_path** | `actuator.leakage.ahu.clg_valve` |
| **severity** | 2 · **confirmation_seconds:** 900 |

```sql
-- confirmation_seconds: 900
SELECT timestamp, equipment_id, clg_valve_pct, sat, sat_sp,
  CASE
    WHEN clg_valve_pct IS NULL OR sat IS NULL OR sat_sp IS NULL THEN false
    WHEN CASE WHEN clg_valve_pct > 1.0 THEN clg_valve_pct/100.0 ELSE clg_valve_pct END > 0.05 THEN false
    WHEN sat < sat_sp - 2.0 THEN true
    ELSE false
  END AS fault_raw
FROM telemetry_pivot
WHERE equipment_id = 'equip:your-ahu'
```

---

### DMP-1 — OA damper leakage

| Field | Value |
|-------|-------|
| **taxonomy_path** | `actuator.leakage.ahu.oa_damper` |
| **severity** | 2 · **confirmation_seconds:** 900 |

```sql
-- confirmation_seconds: 900
SELECT timestamp, equipment_id, oa_damper_pct, oa_t, mat,
  CASE
    WHEN oa_damper_pct IS NULL OR oa_t IS NULL OR mat IS NULL THEN false
    WHEN CASE WHEN oa_damper_pct > 1.0 THEN oa_damper_pct/100.0 ELSE oa_damper_pct END > 0.05 THEN false
    WHEN ABS(mat - oa_t) < 2.0 THEN true
    ELSE false
  END AS fault_raw
FROM telemetry_pivot
WHERE equipment_id = 'equip:your-ahu'
```

---

### VAV-5 — Airflow sensor bias

| Field | Value |
|-------|-------|
| **taxonomy_path** | `terminal.vav.airflow_sensor_bias` |
| **severity** | 2 · **confirmation_seconds:** 900 |

```sql
-- confirmation_seconds: 900
SELECT timestamp, equipment_id, zone_flow, damper_pct,
  CASE
    WHEN zone_flow IS NULL OR damper_pct IS NULL THEN false
    WHEN zone_flow > 50.0
     AND CASE WHEN damper_pct > 1.0 THEN damper_pct/100.0 ELSE damper_pct END < 0.10 THEN true
    ELSE false
  END AS fault_raw
FROM telemetry_pivot
WHERE equipment_id = 'equip:your-vav'
```

---

### PLANT-1 — CHW DP reset missing

| Field | Value |
|-------|-------|
| **taxonomy_path** | `reset.plant.chw.dp_reset_missing` |
| **severity** | 2 · **confirmation_seconds:** 900 |

```sql
-- confirmation_seconds: 900
SELECT timestamp, equipment_id, chw_dp_sp, chw_load_pct, chw_pump_cmd,
  CASE
    WHEN chw_dp_sp IS NULL OR chw_load_pct IS NULL OR chw_pump_cmd IS NULL THEN false
    WHEN chw_pump_cmd <= 0.01 THEN false
    WHEN chw_load_pct < 0.40 AND chw_dp_sp > 18.0 THEN true
    ELSE false
  END AS fault_raw
FROM telemetry_pivot
WHERE equipment_id = 'equip:your-chiller-plant'
```

---

### SP-HIGH / SP-LOW — Occupied zone setpoint drift

```sql
-- SP-HIGH confirmation_seconds: 900
SELECT timestamp, equipment_id, zone_t_sp, occ_mode,
  CASE
    WHEN zone_t_sp IS NULL OR occ_mode IS NULL THEN false
    WHEN occ_mode <> 'occupied' THEN false
    WHEN zone_t_sp > 76.0 THEN true
    ELSE false
  END AS fault_raw
FROM telemetry_pivot WHERE equipment_id = 'equip:your-vav';
```

---

### KPI-1 — Performance score (advisory)

Aggregate confirmed faults by family — see [benchmark strategy](benchmark-strategy.html).

---

## Framework & parity docs

| Doc | Purpose |
|-----|---------|
| [Public taxonomy](taxonomy.html) | Equipment classes, rule families |
| [Rule schema](rule-schema.html) | Declarative source-of-truth |
| [Gap matrix](gap-matrix.html) | Coverage vs public literature |
| [Parity matrix](parity-matrix.html) | SQL ↔ Pandas audit |
| [Roadmap](roadmap.html) | Priority-ranked expansion |
| [Prerequisite macros](prerequisite-macros.html) | Reusable guards |
| [Benchmark strategy](benchmark-strategy.html) | Scenarios & regression |
| [Doc template](doc-template.html) | Per-rule documentation |

---

## Debugging & windowing

| | Historian lookback | Rolling / confirmation |
|---|-------------------|------------------------|
| Set by | SQL FDD test window, validation tab, API | `confirmation_seconds` (default **300**) |
| Typical | 1–24 h for test | 5 min default debounce |

### Debug workflow

1. **Plots** — confirm columns exist and values move
2. **SQL FDD** — run SELECT without `fault_raw` first
3. **Test SQL** — add `fault_raw`, set **`confirmation_seconds: 300`**
4. **Validation tab** — overlay faults on live trends
5. **API** — `GET /api/agent/validate` for historian parity

### Common failures

| Symptom | Check |
|---------|--------|
| Zero rows | Wrong `equipment_id` or empty pivot |
| Always false | NULL inputs; wrong column name |
| Always true | Missing NULL guard; threshold too tight |
| No faults on dashboard | Rule not **activated**; confirmation too long |

### Compare with Pandas

Export the same historian window, run the matching [Pandas section](pandas-cookbook.html), diff flagged timestamps — should align within one poll period.

---

**Next:** [Pandas cookbook](pandas-cookbook.html) — duplicate rules for analyst workflows outside Open-FDD
