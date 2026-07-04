---
title: GL36 algorithm stubs
parent: Rule Cookbook
nav_order: 8
---

# GL36 algorithm stubs (advisory SQL)

Draft **supervisory advisory** patterns for trim-and-respond and plant-enable logic inspired by ASHRAE Guideline 36. These return **fault flags** (sequence unhealthy) — not setpoint writes. For Niagara reference blocks see [README_TRIM_RESPOND](https://github.com/bbartling/niagara4-vibe-code-addict/blob/develop/README_TRIM_RESPOND.md).

Use **confirmation_seconds ≥ 1800** for advisory plant rules — avoid nuisance on transient demand.

---

## Duct static trim advisory

Detect **duct static stuck high** while VAV pressure requests stay low — trim & respond may not be trimming.

**Fault code:** `AHU-TRIM-ADV` · **Confirmation:** 1800 s

```sql
SELECT timestamp, equipment_id, duct_static, vav_press_req_sum,
  CASE
    WHEN duct_static IS NULL OR vav_press_req_sum IS NULL THEN false
    WHEN duct_static > 0.80 AND vav_press_req_sum < 1.0
     AND duct_static > 1.35 THEN true
    ELSE false
  END AS fault_raw
FROM telemetry_pivot
WHERE equipment_id = 'equip:your-ahu'
```

---

## Chiller plant enable advisory

Count AHUs with CHW valve above threshold — plant may be enabled without enough load.

**Fault code:** `CHW-ENABLE-ADV` · **Confirmation:** 900 s

Bind per-AHU valve columns in assignments, or use a pre-aggregated `chw_valve_req_count` historian column:

```sql
SELECT timestamp, equipment_id, chw_valve_req_count,
  CASE
    WHEN chw_valve_req_count IS NULL THEN false
    WHEN chw_valve_req_count >= 2 THEN false
    WHEN chw_valve_req_count < 2 THEN true
    ELSE false
  END AS fault_raw
FROM telemetry_pivot
WHERE equipment_id = 'equip:your-chiller-plant'
```

Per-row multi-AHU pattern (when valves are columns on plant pivot):

```sql
SELECT timestamp, equipment_id,
  CASE
    WHEN ahu1_clg_vlv IS NULL AND ahu2_clg_vlv IS NULL THEN false
    WHEN (COALESCE(ahu1_clg_vlv, 0) >= 95.0)::INT
       + (COALESCE(ahu2_clg_vlv, 0) >= 95.0)::INT
       + (COALESCE(ahu3_clg_vlv, 0) >= 95.0)::INT >= 2 THEN false
    ELSE true
  END AS fault_raw
FROM telemetry_pivot
WHERE equipment_id = 'equip:your-chiller-plant'
```

---

## HWST trim advisory

**HWST trimmed too low** while heating requests remain high.

**Fault code:** `HW-TRIM-ADV` · **Confirmation:** 1800 s

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

---

## CHW plant reset advisory

**CHWST at design cold** with low cooling requests — possible stuck 100% plant loop.

**Fault code:** `CHW-RESET-ADV` · **Confirmation:** 1800 s

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

## VAV zone cooling requests (parity note)

GL36 VAV request levels (0–3) are **algorithm outputs**, not boolean faults. On the edge, model as:

1. **Advisory fault** — zone temp vs cooling SP bands for sustained high demand
2. **Historian column** — export request integer via external analytics (Pandas) for RCx reports

See [Pandas cookbook — VAV cooling requests](pandas-cookbook.html#vav-cooling-request-levels) for off-edge parity.

---

## Testing

1. Bind historian columns in **Model & assignments** (`fdd_input` / Brick types).
2. Paste SQL into **SQL FDD Rules** → **Test** with long `confirmation_seconds`.
3. Overlay on **Live FDD validation** plots before activate.

**Related:** [GL36 AHU rules A–M](gl36-ahu-rules.html) · [Central plants](central-plants.html)
