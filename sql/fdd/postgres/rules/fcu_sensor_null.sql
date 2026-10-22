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
