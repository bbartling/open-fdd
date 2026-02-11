---
title: Points
parent: Concepts
nav_order: 1
---

# Points

Points are time-series references in the Open-FDD data model. They link raw telemetry (BACnet objects, weather sensors) to equipment and Brick semantics.

---

## Structure

Each point has:

| Field | Description |
|-------|-------------|
| `id` | UUID primary key |
| `site_id` | FK to sites |
| `equipment_id` | FK to equipment (nullable) |
| `external_id` | Raw identifier from source (e.g. BACnet object name) |
| `rule_input` | Column name used by FDD rules (e.g. `oat`, `sat`) |
| `brick_type` | Optional Brick class (e.g. `Outside_Air_Temperature_Sensor`) |
| `name` | Optional display name |

---

## Time-series data

Readings are stored in `timeseries_readings`:

| Column | Type | Description |
|--------|------|-------------|
| `point_id` | UUID | FK to points |
| `ts` | timestamp | Timestamp (UTC) |
| `value` | float | Numeric value |

TimescaleDB hypertable, optimized for range scans and downsampling.

---

## Layers and mapping

- **BACnet layer:** `external_id` = BACnet object name (from discovery CSV)
- **Weather layer:** `external_id` = `temp_f`, `rh_pct`, `dewpoint_f`, etc.
- **Rule layer:** `rule_input` maps to DataFrame column names used by YAML rules

The data-model API and Brick TTL coordinate `external_id` ↔ `rule_input` ↔ `brick_type`.

---

## Queries

```sql
SELECT ts, p.external_id, tr.value
FROM timeseries_readings tr
JOIN points p ON p.id = tr.point_id
WHERE p.external_id = 'temp_f'
  AND ts > NOW() - INTERVAL '1 day'
ORDER BY ts DESC;
```
