-- vav7_min_airflow.sql — Min airflow / fixed high flow
-- Phase-1 (#550): SQL screens the under-min-flow branch only.
-- Pandas also faults on rolling "fixed high" flow and high min-flow SP while air is on
-- (params flow_on_min / fixed_flow_* / high_min_flow_sp). Those windows are not ported yet;
-- {{HIGH_MIN_FLOW_SP}} is accepted so registry substitution stays valid but is unused here.
WITH base AS (
  SELECT
    equipment_id,
    timestamp_utc,
    CAST(CASE
      WHEN zone_flow IS NULL OR min_flow_sp IS NULL THEN 0
      WHEN zone_flow < min_flow_sp THEN 1
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
