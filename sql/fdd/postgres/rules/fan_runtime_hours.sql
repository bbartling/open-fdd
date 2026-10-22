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
