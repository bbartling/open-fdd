-- PostgreSQL adaptation. Render numeric template parameters with render_rule.py.
-- Inputs must be scoped to one tenant/site and cadence; see README.md.
-- FCU-MODE-CYCLE — cumulative heat/cool mode transitions in the analysis window.
-- Hours are eligible forward deltas after the change count reaches MODE_CHANGES.
WITH modes AS (
  SELECT
    equipment_id,
    timestamp_utc,
    CASE
      WHEN clg_valve_pct IS NOT NULL AND (CASE WHEN clg_valve_pct > 1.0 THEN clg_valve_pct / 100.0 ELSE clg_valve_pct END) > {{MODE_VALVE_MIN}} THEN -1
      WHEN htg_valve_pct IS NOT NULL AND (CASE WHEN htg_valve_pct > 1.0 THEN htg_valve_pct / 100.0 ELSE htg_valve_pct END) > {{MODE_VALVE_MIN}} THEN 1
      ELSE 0
    END AS mode
  FROM history
),
active_modes AS (
  SELECT equipment_id, timestamp_utc, mode
  FROM modes
  WHERE mode <> 0
),
changes AS (
  SELECT
    equipment_id,
    timestamp_utc,
    mode,
    CASE
      WHEN LAG(mode) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc) IS NOT NULL
       AND mode <> LAG(mode) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc)
      THEN 1 ELSE 0
    END AS changed,
    EXTRACT(EPOCH FROM (
      LEAD(timestamp_utc) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc)
      - timestamp_utc
    )) AS dt_seconds
  FROM active_modes
),
cumulative AS (
  SELECT
    equipment_id,
    SUM(changed) OVER (
      PARTITION BY equipment_id ORDER BY timestamp_utc ROWS UNBOUNDED PRECEDING
    ) AS change_count,
    CASE
      WHEN dt_seconds IS NULL OR dt_seconds <= 0.0 OR dt_seconds > ({{MAX_GAP_HOURS}} * 3600.0)
      THEN 0.0
      ELSE dt_seconds
    END AS held_seconds
  FROM changes
)
SELECT
  equipment_id,
  SUM(CASE WHEN change_count >= {{MODE_CHANGES}} THEN held_seconds ELSE 0.0 END) / 3600.0 AS fault_hours,
  SUM(held_seconds) / 3600.0 AS covered_hours,
  100.0 * SUM(CASE WHEN change_count >= {{MODE_CHANGES}} THEN held_seconds ELSE 0.0 END)
    / NULLIF(SUM(held_seconds), 0.0) AS fault_pct
FROM cumulative
GROUP BY equipment_id;
