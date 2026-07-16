-- fc4_pid_hunting.sql — PID hunting / OS oscillation
-- Simplified SQL variant. Full operating-state transition counting validated in Pandas.
WITH h AS (
  SELECT
    equipment_id,
    timestamp_utc,
    CASE WHEN oa_damper_pct IS NULL THEN NULL WHEN oa_damper_pct > 1.0 THEN oa_damper_pct / 100.0 ELSE oa_damper_pct END AS oa_d,
    CASE WHEN clg_valve_pct IS NULL THEN NULL WHEN clg_valve_pct > 1.0 THEN clg_valve_pct / 100.0 ELSE clg_valve_pct END AS clg,
    CASE WHEN fan_cmd IS NULL THEN NULL WHEN fan_cmd > 1.0 THEN fan_cmd / 100.0 ELSE fan_cmd END AS fan
  FROM history
),
modes AS (
  SELECT
    *,
    CASE
      WHEN fan IS NULL OR fan < 0.05 THEN 0
      WHEN clg IS NOT NULL AND clg > 0.1 THEN 3
      WHEN oa_d IS NOT NULL AND oa_d > 0.5 THEN 2
      ELSE 1
    END AS op_mode
  FROM h
),
base AS (
  SELECT
    equipment_id,
    timestamp_utc,
    CAST(CASE
      WHEN op_mode = 0 THEN 0
      WHEN LAG(op_mode) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc) IS NULL THEN 0
      WHEN op_mode <> LAG(op_mode) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc) THEN 1
      ELSE 0
    END AS INT) AS raw_fault
  FROM modes
),
lagged AS (
  SELECT
    *,
    CASE
      WHEN raw_fault = LAG(raw_fault) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc)
      THEN 0 ELSE 1
    END AS is_new_streak
  FROM base
),
grp AS (
  SELECT
    *,
    SUM(is_new_streak)
      OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS UNBOUNDED PRECEDING) AS streak_id
  FROM lagged
),
ranked AS (
  SELECT
    *,
    ROW_NUMBER() OVER (PARTITION BY equipment_id, streak_id ORDER BY timestamp_utc) AS streak_len
  FROM grp
),
final AS (
  SELECT
    equipment_id,
    CASE WHEN raw_fault = 1 AND streak_len >= {{CONFIRM_ROWS}} THEN 1 ELSE 0 END AS confirmed
  FROM ranked
)
SELECT
  equipment_id,
  SUM(confirmed) * {{POLL_SECONDS}} / 3600.0 AS fault_hours
FROM final
GROUP BY equipment_id;
