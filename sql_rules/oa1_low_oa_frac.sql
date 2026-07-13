-- oa1_low_oa_frac.sql — OA-1 low estimated outdoor air fraction + confirm
WITH h AS (
  SELECT
    *,
    CASE
      WHEN fan_status IS NULL THEN NULL
      WHEN fan_status = TRUE OR fan_status = 1 OR fan_status = 1.0 THEN TRUE
      WHEN TRIM(CAST(fan_status AS VARCHAR)) IN ('1', 'true', 'TRUE', 'on', 'ON', 'yes', 'YES') THEN TRUE
      ELSE FALSE
    END AS fan_status_on
  FROM history
),
base AS (
  SELECT
    equipment_id,
    timestamp_utc,
    CAST(CASE
      WHEN oa_t IS NOT NULL AND rat IS NOT NULL AND mat IS NOT NULL
        AND fan_status_on = TRUE
        AND ABS(rat - oa_t) >= 0.5
        AND ((mat - rat) / NULLIF(oa_t - rat, 0)) < {{MIN_OA_FRAC}}
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
