-- fc14_chw_coil_dt_inactive.sql — FC14 CHW coil delta-T when inactive + confirm
WITH h AS (
  SELECT * FROM history
),
base AS (
  SELECT
    equipment_id,
    timestamp_utc,
    CAST(CASE
      WHEN clg_coil_enter_t IS NOT NULL AND clg_coil_leave_t IS NOT NULL
        AND (clg_coil_enter_t - clg_coil_leave_t) >= 2.179 + 0.55
        AND (
          (COALESCE(CASE WHEN oa_damper_pct IS NULL THEN NULL WHEN oa_damper_pct > 1.0 THEN oa_damper_pct / 100.0 ELSE oa_damper_pct END, 0.0) > {{AHU_MIN_OA_DPR}} AND COALESCE(CASE WHEN clg_valve_pct IS NULL THEN NULL WHEN clg_valve_pct > 1.0 THEN clg_valve_pct / 100.0 ELSE clg_valve_pct END, 0.0) < 0.1)
          OR (COALESCE(CASE WHEN htg_valve_pct IS NULL THEN NULL WHEN htg_valve_pct > 1.0 THEN htg_valve_pct / 100.0 ELSE htg_valve_pct END, 0.0) > 0 AND COALESCE(CASE WHEN fan_cmd IS NULL THEN NULL WHEN fan_cmd > 1.0 THEN fan_cmd / 100.0 ELSE fan_cmd END, 0.0) > 0)
        )
      THEN 1 ELSE 0 END AS INT) AS raw_fault
  FROM h
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
