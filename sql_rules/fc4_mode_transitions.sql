-- fc4_mode_transitions.sql — FC4 operating-mode transition hunting + confirm
WITH h AS (
  SELECT
    equipment_id,
    timestamp_utc,
    COALESCE(CASE WHEN fan_cmd IS NULL THEN NULL WHEN fan_cmd > 1.0 THEN fan_cmd / 100.0 ELSE fan_cmd END, 0.0) AS fan,
    COALESCE(CASE WHEN htg_valve_pct IS NULL THEN NULL WHEN htg_valve_pct > 1.0 THEN htg_valve_pct / 100.0 ELSE htg_valve_pct END, 0.0) AS htg,
    COALESCE(CASE WHEN clg_valve_pct IS NULL THEN NULL WHEN clg_valve_pct > 1.0 THEN clg_valve_pct / 100.0 ELSE clg_valve_pct END, 0.0) AS clg,
    COALESCE(CASE WHEN oa_damper_pct IS NULL THEN NULL WHEN oa_damper_pct > 1.0 THEN oa_damper_pct / 100.0 ELSE oa_damper_pct END, 0.0) AS econ
  FROM history
),
modes AS (
  SELECT
    equipment_id,
    timestamp_utc,
    CASE
      WHEN htg > 0 AND clg = 0 AND fan > 0 AND econ <= {{AHU_MIN_OA_DPR}} THEN 'htg'
      WHEN htg = 0 AND clg = 0 AND fan > 0 AND econ > {{AHU_MIN_OA_DPR}} THEN 'econ'
      WHEN htg = 0 AND clg > 0 AND fan > 0 AND econ > {{AHU_MIN_OA_DPR}} THEN 'econ_mech'
      WHEN htg = 0 AND clg > 0 AND fan > 0 AND econ <= {{AHU_MIN_OA_DPR}} THEN 'mech'
      ELSE 'other'
    END AS os_mode
  FROM h
),
trans AS (
  SELECT
    equipment_id,
    timestamp_utc,
    os_mode,
    CASE
      WHEN os_mode <> LAG(os_mode) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc)
       AND LAG(os_mode) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc) IS NOT NULL
      THEN 1 ELSE 0
    END AS mode_change
  FROM modes
),
base AS (
  SELECT
    equipment_id,
    timestamp_utc,
    CAST(CASE
      WHEN SUM(mode_change) OVER (
        PARTITION BY equipment_id
        ORDER BY timestamp_utc
        ROWS BETWEEN {{WINDOW_ROWS_MINUS_ONE}} PRECEDING AND CURRENT ROW
      ) > {{DELTA_OS_MAX}}
      THEN 1 ELSE 0 END AS INT) AS raw_fault
  FROM trans
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
