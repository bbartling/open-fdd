---
title: DataFusion SQL cookbook
parent: Rule Cookbook
nav_order: 1
---

# DataFusion SQL cookbook

**Open-FDD edge runtime.** Copy-paste rules into the **SQL FDD Rules** tab or `POST /api/fdd-rules/{id}/test-sql`.

## Concepts

| Term | Meaning |
|------|---------|
| `telemetry_pivot` | Wide historian table: `timestamp`, `equipment_id`, FDD input columns (`oa_t`, `sat`, …) |
| `telemetry` | Long format (optional) — use pivot for most HVAC rules |
| `fault_raw` | Boolean — instantaneous fault condition (required) |
| `confirmation_seconds` | API applies minimum duration **after** SQL (debounce) |

Column names come from your **Haystack assignment graph**, not BACnet instance numbers. See [Haystack → SQL columns](haystack-assignments.html).

## Rule template

```sql
SELECT
  timestamp,
  equipment_id,
  /* optional: expose inputs for debugging */
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

---

## 1. OA temperature out of range

**Fault code:** `OA_TEMP_OUT_OF_RANGE` · **Confirmation:** 300 s

```sql
SELECT timestamp, equipment_id, oa_t,
  CASE
    WHEN oa_t IS NULL THEN false
    WHEN oa_t < 40.0 OR oa_t > 110.0 THEN true
    ELSE false
  END AS fault_raw
FROM telemetry_pivot
WHERE equipment_id = 'equip:validation'
```

Builder API:

```bash
curl -s -X POST http://127.0.0.1:8080/api/fdd-rules/builder-sql \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"input":"oa_t","operator":"range","low":40,"high":110,"equipment_id":"equip:validation"}' | jq '.sql'
```

---

## 2. SAT deviation from setpoint

**Fault code:** `SAT_DEVIATION_HIGH` · **Confirmation:** 600 s

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

---

## 3. Duct static pressure high

**Fault code:** `DUCT_STATIC_HIGH` · **Confirmation:** 300 s

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

---

## 4. Duct static low at full fan (GL36 Rule A)

**Fault code:** `AHU-A` · **Confirmation:** 300 s

```sql
SELECT timestamp, equipment_id, duct_static, duct_static_sp, fan_cmd,
  CASE
    WHEN duct_static IS NULL OR duct_static_sp IS NULL OR fan_cmd IS NULL THEN false
    WHEN duct_static < duct_static_sp - 0.12
     AND fan_cmd >= 0.87 THEN true
    ELSE false
  END AS fault_raw
FROM telemetry_pivot
WHERE equipment_id = 'equip:your-ahu'
```

Normalize `fan_cmd` to 0–1 in assignments if your site uses 0–100 %.

---

## 5. Mixed air below OAT/RAT envelope (GL36 Rule B)

**Fault code:** `AHU-D` · **Confirmation:** 600 s

```sql
SELECT timestamp, equipment_id, mat, oat, rat, fan_cmd,
  CASE
    WHEN mat IS NULL OR oat IS NULL OR rat IS NULL OR fan_cmd IS NULL THEN false
    WHEN fan_cmd <= 0.01 THEN false
    WHEN mat - 1.15 < LEAST(rat - 1.15, oat - 1.15) THEN true
    ELSE false
  END AS fault_raw
FROM telemetry_pivot
WHERE equipment_id = 'equip:your-ahu'
```

---

## 6. Mixed air above OAT/RAT envelope (GL36 Rule C)

**Fault code:** `AHU-D` · **Confirmation:** 600 s

```sql
SELECT timestamp, equipment_id, mat, oat, rat, fan_cmd,
  CASE
    WHEN mat IS NULL OR oat IS NULL OR rat IS NULL OR fan_cmd IS NULL THEN false
    WHEN fan_cmd <= 0.01 THEN false
    WHEN mat - 1.15 > GREATEST(rat + 1.15, oat + 1.15) THEN true
    ELSE false
  END AS fault_raw
FROM telemetry_pivot
WHERE equipment_id = 'equip:your-ahu'
```

---

## 7. Discharge cold when heating commanded (GL36 Rule D)

**Fault code:** `AHU-B` · **Confirmation:** 600 s

```sql
SELECT timestamp, equipment_id, sat, mat, htg_valve_pct, fan_cmd,
  CASE
    WHEN sat IS NULL OR mat IS NULL THEN false
    WHEN htg_valve_pct IS NULL OR fan_cmd IS NULL THEN false
    WHEN fan_cmd <= 0.01 OR htg_valve_pct <= 0.01 THEN false
    WHEN sat + 1.15 <= mat - 1.15 + 0.55 THEN true
    ELSE false
  END AS fault_raw
FROM telemetry_pivot
WHERE equipment_id = 'equip:your-ahu'
```

---

## 8. SAT low with full heating (GL36 Rule E)

**Fault code:** `AHU-C` · **Confirmation:** 600 s

```sql
SELECT timestamp, equipment_id, sat, sat_sp, htg_valve_pct, fan_cmd,
  CASE
    WHEN sat IS NULL OR sat_sp IS NULL THEN false
    WHEN htg_valve_pct IS NULL OR fan_cmd IS NULL THEN false
    WHEN fan_cmd <= 0.01 THEN false
    WHEN sat < sat_sp - 1.0 AND htg_valve_pct > 0.9 THEN true
    ELSE false
  END AS fault_raw
FROM telemetry_pivot
WHERE equipment_id = 'equip:your-ahu'
```

---

## 9. Zone temperature comfort band

**Fault code:** `ZONE_TEMP_OUT_OF_BAND` · **Confirmation:** 900 s

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

---

## 10. Economizer stuck closed

**Fault code:** `ECONOMIZER_STUCK_CLOSED` · **Confirmation:** 600 s

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

---

## 11. Heating and cooling simultaneous

**Fault code:** `HEAT_COOL_SIMULTANEOUS` · **Confirmation:** 300 s

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

---

## 12. Fan off but duct still warm

**Fault code:** `FAN_OFF_DUCT_WARM` · **Confirmation:** 600 s

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

## 13. OA humidity out of range

**Fault code:** `OA_HUMIDITY_OUT_OF_RANGE` · **Confirmation:** 300 s

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

---

## 14. Night setback miss

**Fault code:** `NIGHT_SETBACK_MISS` · **Confirmation:** 1800 s

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

---

## 15. Low chilled-water delta-T

**Fault code:** `CHW-DT-001` · **Confirmation:** 900 s

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

---

## 16. Stale data (no recent samples)

Use long-format `telemetry` or pivot with last timestamp per equipment:

```sql
SELECT equipment_id,
  MAX(timestamp) AS last_ts
FROM telemetry_pivot
GROUP BY equipment_id
HAVING MAX(timestamp) < NOW() - INTERVAL '30' MINUTE
```

Adapt interval syntax to your DataFusion version; test in `/sql-fdd` before activate.

---

## When SQL is enough vs not

| Pattern | DataFusion SQL | Use Pandas off-edge instead |
|---------|----------------|----------------------------|
| Thresholds, spreads, envelopes | ✅ Best fit | Parity testing |
| `confirmation_seconds` debounce | ✅ Built-in API | Manual rolling in notebook |
| Multi-sample flatline / PID hunting | ⚠️ Limited windows | ✅ Rolling in Pandas |
| ML feature prep | ❌ | ✅ Pandas / Polars |

See [Pandas cookbook](pandas-cookbook.html) for rolling-window equivalents.

---

## Workflow: draft → test → activate

1. Save rule: `POST /api/fdd-rules` with `review_status: draft`
2. Test: `POST /api/fdd-rules/{id}/test-sql` with `confirmation_seconds`
3. Integrator approves in UI
4. Activate: `POST /api/fdd-rules/{id}/activate`

Link rules in **FDD Wires** graph: `driver_point → model_point → fdd_input → sql_rule → confirmation → fault_output`.

**Next:** [Pandas cookbook](pandas-cookbook.html) · [Fault confirmation](fault-confirmation.html) · [GL36 reference](gl36-ahu-rules.html)
