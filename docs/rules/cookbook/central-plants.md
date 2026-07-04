---
title: Central plants
parent: Rule Cookbook
nav_order: 6
---

# Central plant rules

Chiller, condenser water, cooling tower, and boiler patterns use the same historian + SQL model as air-side equipment.

## Starter fault codes

| Code | Pattern | SQL cookbook |
|------|---------|--------------|
| `CHW-DT-001` | Low chilled-water ΔT | [§15](datafusion-sql-cookbook.html#15-low-chilled-water-delta-t) |
| `CHW-DP-001` | CHW DP reset stuck high | Compare `chw_dp` vs `chw_dp_sp` |
| `CH-C` | Cooling coil ΔT when valve closed | CHW drop with `clg_valve_pct < 0.1` |
| `CH-D` | CHW/HW sensor bounds | [Sensor validation](sensor-validation.html) |

## Required FDD inputs (example)

| Role | Typical column |
|------|----------------|
| CHW supply temp | `chw_supply_t` |
| CHW return temp | `chw_return_t` |
| CHW differential pressure | `chw_dp` |
| CHW DP setpoint | `chw_dp_sp` |
| Pump command | `chw_pump_cmd` |
| Tower fan / condenser | `ct_fan_cmd`, `condenser_t` |

Map via [Haystack assignments](haystack-assignments.html) — names vary by site.

## Low ΔT syndrome — SQL

```sql
SELECT timestamp, equipment_id,
  chw_supply_t, chw_return_t, chw_pump_cmd,
  CASE
    WHEN chw_supply_t IS NULL OR chw_return_t IS NULL THEN false
    WHEN chw_pump_cmd IS NOT true THEN false
    WHEN (chw_return_t - chw_supply_t) < 4.0 THEN true
    ELSE false
  END AS fault_raw
FROM telemetry_pivot
WHERE equipment_id = 'equip:your-plant'
```

## Pandas

[§8 Low chilled-water delta-T](pandas-cookbook.html#8-low-chilled-water-delta-t)

## Synthetic test

Validate with injected historian scenarios (`POST /api/fdd/inject-scenario`) before enabling on live plant points.
