-- vav_ahu_leave.sql — VAV leave vs parent AHU SAT (fedBy)
WITH base AS (
  SELECT
    equipment_id,
    timestamp_utc,
    CAST(CASE
      WHEN vav_discharge_t IS NULL OR ahu_sat IS NULL THEN 0
      WHEN COALESCE(zone_flow, 0) > {{FLOW_ON_MIN}}
       AND ABS(vav_discharge_t - ahu_sat) > {{DELTA_F}} THEN 1
      ELSE 0
    END AS INT) AS raw_fault
  FROM history
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
