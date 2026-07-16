-- sv_stale.sql — Stale data (no fresh samples)
WITH mx AS (
  SELECT MAX(timestamp_utc) AS max_ts FROM history
),
base AS (
  SELECT
    h.equipment_id,
    h.timestamp_utc,
    CAST(CASE
      WHEN CAST(EXTRACT(EPOCH FROM (mx.max_ts - h.timestamp_utc)) AS DOUBLE)
           > {{STALE_HOURS}} * 3600.0 THEN 1
      ELSE 0
    END AS INT) AS raw_fault
  FROM history h
  CROSS JOIN mx
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
