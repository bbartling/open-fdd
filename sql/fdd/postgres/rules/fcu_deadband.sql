-- PostgreSQL adaptation. Render numeric template parameters with render_rule.py.
-- Inputs must be scoped to one tenant/site and cadence; see README.md.
-- FCU-DEADBAND — pass-through FCU setpoints remain site-native Celsius.
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
     AND cooling_sp - heating_sp < {{DEADBAND}}
    THEN held_seconds ELSE 0.0
  END) / 3600.0 AS fault_hours,
  SUM(held_seconds) / 3600.0 AS covered_hours,
  100.0 * SUM(CASE
    WHEN cooling_sp IS NOT NULL AND heating_sp IS NOT NULL
     AND cooling_sp - heating_sp < {{DEADBAND}}
    THEN held_seconds ELSE 0.0
  END) / NULLIF(SUM(held_seconds), 0.0) AS fault_pct
FROM held
GROUP BY equipment_id;
