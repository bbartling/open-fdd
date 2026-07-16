-- sv_rate.sql — Context-aware sensor rate of change
-- Simplified SQL variant. Full context-aware rate logic validated in Pandas.
-- Screening placeholder: does not latch until site-tuned profiles are coded.
WITH h AS (
  SELECT
    equipment_id,
    timestamp_utc,
    oa_t,
    LAG(oa_t) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc) AS prev_oa_t,
    LAG(timestamp_utc) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc) AS prev_ts
  FROM history
),
base AS (
  SELECT
    equipment_id,
    timestamp_utc,
    CAST(CASE
      -- Simplified screen: sustained |ΔT| > 5°F/min between samples (tune via params unused here)
      WHEN oa_t IS NULL OR prev_oa_t IS NULL OR prev_ts IS NULL THEN 0
      WHEN ABS(oa_t - prev_oa_t) > 5.0
       AND CAST(EXTRACT(EPOCH FROM (timestamp_utc - prev_ts)) AS DOUBLE) <= {{PERSISTENCE_MIN}} * 60.0
      THEN 1
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
