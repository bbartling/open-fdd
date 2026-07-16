-- fc15_hw_coil_dt_inactive.sql — HW coil ΔT when inactive (GL36 M)
-- Simplified: uses MAT/SAT proxy when dedicated HW coil temps absent.
WITH h AS (
  SELECT
    equipment_id,
    timestamp_utc,
    mat, sat,
    CASE WHEN htg_valve_pct IS NULL THEN 0.0 WHEN htg_valve_pct > 1.0 THEN htg_valve_pct / 100.0 ELSE htg_valve_pct END AS htg,
    CASE WHEN fan_cmd IS NULL THEN 0.0 WHEN fan_cmd > 1.0 THEN fan_cmd / 100.0 ELSE fan_cmd END AS fan
  FROM history
),
base AS (
  SELECT
    equipment_id,
    timestamp_utc,
    CAST(CASE
      WHEN mat IS NULL OR sat IS NULL THEN 0
      WHEN fan < 0.05 THEN 0
      WHEN htg > 0.01 THEN 0
      WHEN ABS(sat - mat) >= SQRT(2.0 * {{MIX_TOL}} * {{MIX_TOL}}) + 0.55 THEN 1
      ELSE 0
    END AS INT) AS raw_fault
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
