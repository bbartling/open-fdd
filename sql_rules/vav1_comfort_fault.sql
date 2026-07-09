-- vav1_comfort_fault.sql — zone comfort band with confirm window (Open-FDD parity)
WITH base AS (
  SELECT
    equipment_id,
    timestamp_utc,
    CAST(CASE WHEN zone_t < {{ZONE_T_LO}} OR zone_t > {{ZONE_T_HI}} THEN 1 ELSE 0 END AS INT) AS raw_fault
  FROM history
  WHERE zone_t IS NOT NULL
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
    timestamp_utc,
    CASE WHEN raw_fault = 1 AND streak_len >= {{CONFIRM_ROWS}} THEN 1 ELSE 0 END AS confirmed
  FROM ranked
)
SELECT
  equipment_id,
  SUM(confirmed) * {{POLL_SECONDS}} / 3600.0 AS fault_hours,
  100.0 * SUM(confirmed) / COUNT(*) AS fault_pct
FROM final
GROUP BY equipment_id;
