-- econ4_low_oa_frac.sql — ECON-4 low estimated OA fraction + confirm (600s)
WITH h AS (
  SELECT
    equipment_id,
    timestamp_utc,
    mat,
    rat,
    oa_t,
    COALESCE(CASE WHEN fan_cmd IS NULL THEN 0.0 WHEN fan_cmd > 1.0 THEN fan_cmd / 100.0 ELSE fan_cmd END, 0.0) AS fan
  FROM history
),
base AS (
  SELECT
    equipment_id,
    timestamp_utc,
    CAST(CASE
      WHEN fan > 0.01 AND mat IS NOT NULL AND rat IS NOT NULL AND oa_t IS NOT NULL
       AND ABS(rat - oa_t) > 2.2
       AND ((mat - rat) / NULLIF(oa_t - rat, 0)) * 100.0 < {{OA_MIN_PCT}}
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
