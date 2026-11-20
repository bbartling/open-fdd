-- PostgreSQL adaptation. Render numeric template parameters with render_rule.py.
-- Inputs must be scoped to one tenant/site and cadence; see README.md.
-- FCU-MODE-CYCLE — cumulative heat/cool mode transitions in the analysis window.
-- Hours are eligible forward deltas after the change count reaches MODE_CHANGES.
-- #1642: each sample holds the time to the NEXT sample of any mode (forward sample-and-hold); the change count runs
-- over the heating / cooling samples only. An idle sample is never fault time, and an active sample no longer holds
-- the idle stretch after it (it used to own the gap to the next active sample), as pandas fcu_mode_cycle.
WITH modes AS (
  SELECT
    equipment_id,
    timestamp_utc,
    CASE
      WHEN clg_valve_pct IS NOT NULL AND clg_valve_pct > {{MODE_VALVE_MIN}} THEN -1
      WHEN htg_valve_pct IS NOT NULL AND htg_valve_pct > {{MODE_VALVE_MIN}} THEN 1
      ELSE 0
    END AS mode,
    EXTRACT(EPOCH FROM (
      LEAD(timestamp_utc) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc)
      - timestamp_utc
    )) AS dt_seconds
  FROM history
),
held AS (
  SELECT
    equipment_id,
    timestamp_utc,
    mode,
    CASE
      WHEN dt_seconds IS NULL OR dt_seconds <= 0.0 OR dt_seconds > ({{MAX_GAP_HOURS}} * 3600.0)
      THEN 0.0
      ELSE dt_seconds
    END AS held_seconds
  FROM modes
),
changes AS (
  SELECT
    equipment_id,
    timestamp_utc,
    held_seconds,
    CASE
      WHEN LAG(mode) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc) IS NOT NULL
       AND mode <> LAG(mode) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc)
      THEN 1 ELSE 0
    END AS changed
  FROM held
  WHERE mode <> 0
),
cumulative AS (
  SELECT
    equipment_id,
    held_seconds,
    SUM(changed) OVER (
      PARTITION BY equipment_id ORDER BY timestamp_utc ROWS UNBOUNDED PRECEDING
    ) AS change_count
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
