# SQL HVAC FDD rule cookbook (DataFusion)

Open-FDD **3.2 Rust edge** runs fault detection with **DataFusion SQL** only (no PyArrow rule functions on the edge path). This cookbook replaces the legacy Python `rule-cookbook.zip` with SQL equivalents.

## Concepts

| Term | Meaning |
| --- | --- |
| `telemetry_pivot` | Wide telemetry table (timestamp, equipment_id, FDD input columns) |
| `fault_raw` | Boolean column — instantaneous fault condition |
| `confirmation_seconds` | Minimum duration before a fault latches (API applies after SQL) |
| `builder-sql` | API generates SQL from `{input, operator, value, equipment_id}` |

## Safety

- **SELECT only** — DDL/DML rejected by `sql_safety` module
- Rules must expose `fault_raw` (or alias) for confirmation engine
- Integrator role required to **activate** rules

## Test a rule

```bash
curl -s -X POST http://127.0.0.1:8080/api/fdd-rules/RULE_ID/test-sql \
  -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"sql":"<SQL>","confirmation_seconds":300}' | jq '.ok, .engine, .confirmation'
```

---

## 1. OA temperature out of range

**Fault code:** `OA_TEMP_OUT_OF_RANGE`  
**Inputs:** `oa_t`  
**Confirmation:** 300 s

```sql
SELECT
  timestamp,
  equipment_id,
  oa_t,
  CASE
    WHEN oa_t IS NULL THEN false
    WHEN oa_t < 40.0 THEN true
    WHEN oa_t > 110.0 THEN true
    ELSE false
  END AS fault_raw
FROM telemetry_pivot
WHERE equipment_id = 'AHU-1'
```

Builder API:

```bash
curl -s -X POST http://127.0.0.1:8080/api/fdd-rules/builder-sql \
  -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"input":"oa_t","operator":"range","low":40,"high":110,"equipment_id":"AHU-1"}' | jq '.sql'
```

---

## 2. SAT deviation (supply air vs setpoint)

**Fault code:** `SAT_DEVIATION_HIGH`  
**Inputs:** `sat`, `sat_sp`  
**Confirmation:** 600 s

```sql
SELECT
  timestamp,
  equipment_id,
  sat,
  sat_sp,
  CASE
    WHEN sat IS NULL OR sat_sp IS NULL THEN false
    WHEN ABS(sat - sat_sp) > 5.0 THEN true
    ELSE false
  END AS fault_raw
FROM telemetry_pivot
WHERE equipment_id = 'AHU-1'
```

---

## 3. Duct static pressure high

**Fault code:** `DUCT_STATIC_HIGH`  
**Inputs:** `duct_static`, `duct_static_sp`  
**Confirmation:** 300 s

```sql
SELECT
  timestamp,
  equipment_id,
  duct_static,
  duct_static_sp,
  CASE
    WHEN duct_static IS NULL OR duct_static_sp IS NULL THEN false
    WHEN duct_static > duct_static_sp + 0.25 THEN true
    ELSE false
  END AS fault_raw
FROM telemetry_pivot
WHERE equipment_id = 'AHU-1'
```

---

## 4. Zone temperature comfort band

**Fault code:** `ZONE_TEMP_OUT_OF_BAND`  
**Inputs:** `zone_t`  
**Confirmation:** 900 s

```sql
SELECT
  timestamp,
  equipment_id,
  zone_t,
  CASE
    WHEN zone_t IS NULL THEN false
    WHEN zone_t < 68.0 OR zone_t > 76.0 THEN true
    ELSE false
  END AS fault_raw
FROM telemetry_pivot
WHERE equipment_id = 'VAV-1'
```

---

## 5. AHU running with OA damper closed (economizer fault)

**Fault code:** `ECONOMIZER_STUCK_CLOSED`  
**Inputs:** `fan_cmd`, `oa_damper_pct`, `oa_t`, `oa_h`  
**Confirmation:** 600 s

```sql
SELECT
  timestamp,
  equipment_id,
  fan_cmd,
  oa_damper_pct,
  CASE
    WHEN fan_cmd = true AND oa_damper_pct < 5.0 AND oa_t > 55.0 THEN true
    ELSE false
  END AS fault_raw
FROM telemetry_pivot
WHERE equipment_id = 'AHU-1'
```

---

## 6. Heating valve open while cooling mode

**Fault code:** `HEAT_COOL_SIMULTANEOUS`  
**Inputs:** `htg_valve_pct`, `clg_valve_pct`, `occ_mode`  
**Confirmation:** 300 s

```sql
SELECT
  timestamp,
  equipment_id,
  htg_valve_pct,
  clg_valve_pct,
  CASE
    WHEN htg_valve_pct > 10.0 AND clg_valve_pct > 10.0 THEN true
    ELSE false
  END AS fault_raw
FROM telemetry_pivot
WHERE equipment_id = 'AHU-1'
```

---

## 7. Fan off but discharge air moving (stuck fan / sensor)

**Fault code:** `FAN_OFF_DUCT_WARM`  
**Inputs:** `fan_cmd`, `duct_t`, `oa_t`  
**Confirmation:** 600 s

```sql
SELECT
  timestamp,
  equipment_id,
  fan_cmd,
  duct_t,
  oa_t,
  CASE
    WHEN fan_cmd = false AND duct_t > oa_t + 15.0 THEN true
    ELSE false
  END AS fault_raw
FROM telemetry_pivot
WHERE equipment_id = 'AHU-1'
```

---

## 8. Humidity out of range (OA)

**Fault code:** `OA_HUMIDITY_OUT_OF_RANGE`  
**Inputs:** `oa_h`  
**Confirmation:** 300 s

```sql
SELECT
  timestamp,
  equipment_id,
  oa_h,
  CASE
    WHEN oa_h IS NULL THEN false
    WHEN oa_h < 10.0 OR oa_h > 95.0 THEN true
    ELSE false
  END AS fault_raw
FROM telemetry_pivot
WHERE equipment_id = 'AHU-1'
```

---

## 9. Night setback not achieved

**Fault code:** `NIGHT_SETBACK_MISS`  
**Inputs:** `zone_t`, `occ_mode`  
**Confirmation:** 1800 s

```sql
SELECT
  timestamp,
  equipment_id,
  zone_t,
  occ_mode,
  CASE
    WHEN occ_mode = 'unoccupied' AND zone_t > 78.0 THEN true
    ELSE false
  END AS fault_raw
FROM telemetry_pivot
WHERE equipment_id = 'VAV-1'
```

---

## 10. Static pressure below minimum (low flow)

**Fault code:** `DUCT_STATIC_LOW`  
**Inputs:** `duct_static`, `fan_cmd`  
**Confirmation:** 300 s

```sql
SELECT
  timestamp,
  equipment_id,
  duct_static,
  fan_cmd,
  CASE
    WHEN fan_cmd = true AND duct_static < 0.5 THEN true
    ELSE false
  END AS fault_raw
FROM telemetry_pivot
WHERE equipment_id = 'AHU-1'
```

---

## Workflow: draft → approve → activate

1. **Agent or integrator** saves rule: `POST /api/fdd-rules` with `review_status: draft`
2. **Test SQL:** `POST /api/fdd-rules/{id}/test-sql`
3. **Integrator approves** in UI or sets `review_status: approved`
4. **Activate:** `POST /api/fdd-rules/{id}/activate` (integrator JWT only)

## FDD Wires integration

Link rules in the visual graph: `driver_point → model_point → fdd_input → sql_rule → confirmation_timer → fault_output`.

See [fdd-wires.md](../verification/fdd-wires.md) and [AI Haystack guide](../ai-agent/haystack-and-assignments.md).

## Legacy Python cookbook

The Python-era PyArrow rule functions and ZIP cookbook remain in git history for **off-edge** `pip install open-fdd` use. The Rust edge path is **SQL-only** for runtime FDD.
