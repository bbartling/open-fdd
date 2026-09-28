-- FCU-MODE-CYCLE — cumulative heat/cool mode transitions in the analysis window
WITH modes AS (
  SELECT equipment_id, timestamp_utc,
    CASE
      WHEN clg_valve_pct IS NOT NULL AND (CASE WHEN clg_valve_pct > 1.0 THEN clg_valve_pct / 100.0 ELSE clg_valve_pct END) > {{MODE_VALVE_MIN}} THEN -1
      WHEN htg_valve_pct IS NOT NULL AND (CASE WHEN htg_valve_pct > 1.0 THEN htg_valve_pct / 100.0 ELSE htg_valve_pct END) > {{MODE_VALVE_MIN}} THEN 1
      ELSE 0
    END AS mode
  FROM history
), active_modes AS (
  SELECT equipment_id, timestamp_utc, mode
  FROM modes WHERE mode <> 0
), changes AS (
  SELECT equipment_id, timestamp_utc, mode,
    CASE WHEN LAG(mode) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc) IS NOT NULL
      AND mode <> LAG(mode) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc)
      THEN 1 ELSE 0 END AS changed
  FROM active_modes
), cumulative AS (
  SELECT equipment_id, timestamp_utc,
    SUM(changed) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS UNBOUNDED PRECEDING) AS change_count
  FROM changes
)
SELECT equipment_id,
  SUM(CASE WHEN change_count >= {{MODE_CHANGES}} THEN 1 ELSE 0 END)
    * {{POLL_SECONDS}} / 3600.0 AS fault_hours
FROM cumulative
GROUP BY equipment_id;

