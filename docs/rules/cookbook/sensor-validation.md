---
title: Sensor validation
parent: Rule Cookbook
nav_order: 4
---

# Sensor validation patterns

Data-quality faults (bounds, flatline, rate-of-change, mixing envelope) should be **gated** with equipment state (fan on, occupied, valve open) where appropriate.

## Default bounds (°F / imperial)

Tune per site in rule params or SQL literals.

| Sensor kind | Min | Max | Flatline tol | Max Δ/hr | Typical code |
|-------------|-----|-----|--------------|----------|--------------|
| Zone temp | 55 | 90 | 0.10 | 4.0 | VAV-C |
| Supply air temp | 50 | 110 | 0.15 | 8.0 | AHU-C |
| Return air temp | 55 | 95 | 0.10 | 3.0 | AHU-D |
| Mixed air temp | 40 | 110 | 0.15 | 6.0 | AHU-D |
| Outdoor air temp | −40 | 130 | 0.10 | 12.0 | BLD-B |
| Duct static (inH₂O) | −0.5 | 3.0 | 0.02 | 0.5 | AHU-A |
| Relative humidity (%) | 0 | 100 | 1.0 | 15.0 | DC-C |
| CHW temp | 40 | 90 | 0.10 | 4.0 | CH-D |
| CO₂ (ppm, occupied) | 400 | 1000 | 5.0 | 200 | VAV-B |

Metric sites: scale thresholds (e.g. 55 °F ≈ 12.8 °C).

## Bounds — DataFusion SQL

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

## Mixing envelope

When OAT, RAT, and MAT are all present, prefer envelope checks over RAT-only bounds. See [GL36 Rules B & C](datafusion-sql-cookbook.html#5-mixed-air-below-oatr-envelope-gl36-rule-b) in the SQL cookbook.

## Flatline & rate-of-change

Rolling windows are easier in [Pandas](pandas-cookbook.html#5-flatline-stuck-sensor--12-samples--1-h--5-min). On edge, use **confirmation_seconds** with simpler threshold rules, or pre-compute features in historian ETL.

## Symptom → pattern

| Symptom | Pattern | Codes |
|---------|---------|-------|
| Flatline ~1 h | Rolling min ≈ max | VAV-C, AHU-C, BLD-B |
| Single sample OOB | Threshold | sensor-specific |
| Spike between polls | Rate of change | BLD-B |
| No new samples | Stale query | BLD-D |
| MAT outside [OAT,RAT] | Mixing envelope | AHU-D |
