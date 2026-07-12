-- wx1_temp_spike.sql — WX-1 OA temperature spike + confirm
WITH h AS (
  SELECT equipment_id, timestamp_utc, oa_t FROM history
),
w AS (
  SELECT
    equipment_id,
    timestamp_utc,
    oa_t,
    ABS(oa_t - LAG(oa_t) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc)) AS oa_jump
  FROM h
),
base AS (
  SELECT
    equipment_id,
    timestamp_utc,
    CAST(CASE
      WHEN oa_t IS NOT NULL AND oa_jump > {{SPIKE_LIMIT}}
      THEN 1 ELSE 0 END AS INT) AS raw_fault
  FROM w
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
