-- ahu_ducthi.sql — Duct static pressure high
-- Equation: static > SP + DUCT_HIGH_MARGIN.
-- Gate: fan-on from fan_status then fan_cmd. Missing fan stays NULL
-- (do not ELSE 1). Pressure-on substitutes only when fan proof is absent,
-- never when status/cmd is proven 0 (frozen overnight static).
WITH h AS (
  SELECT
    equipment_id,
    timestamp_utc,
    duct_static, duct_static_sp,
    CASE WHEN fan_cmd IS NULL THEN NULL WHEN fan_cmd > 1.0 THEN fan_cmd / 100.0 ELSE fan_cmd END AS fan,
    CASE
      WHEN fan_status IS NOT NULL THEN CASE WHEN fan_status > 0.05 THEN 1 ELSE 0 END
      WHEN fan_cmd IS NOT NULL THEN CASE WHEN (CASE WHEN fan_cmd > 1.0 THEN fan_cmd / 100.0 ELSE fan_cmd END) > 0.01 THEN 1 ELSE 0 END
      ELSE NULL
    END AS fan_on
  FROM history
),
base AS (
  SELECT
    equipment_id,
    timestamp_utc,
    CAST(CASE
      WHEN duct_static IS NULL OR duct_static_sp IS NULL THEN 0
      WHEN fan_on = 0 THEN 0
      WHEN fan_on = 1 AND duct_static > duct_static_sp + {{DUCT_HIGH_MARGIN}} THEN 1
      WHEN fan_on IS NULL
           AND ABS(duct_static) > {{PRESSURE_ON_MIN}}
           AND duct_static > duct_static_sp + {{DUCT_HIGH_MARGIN}} THEN 1
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
