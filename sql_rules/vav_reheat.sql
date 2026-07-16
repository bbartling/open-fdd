-- vav_reheat.sql — Reheat valve stuck / no temp rise
WITH h AS (
  SELECT
    equipment_id,
    timestamp_utc,
    vav_discharge_t, vav_inlet_t, zone_flow,
    CASE WHEN reheat_valve_pct IS NULL THEN NULL WHEN reheat_valve_pct > 1.0 THEN reheat_valve_pct / 100.0 ELSE reheat_valve_pct END AS rh
  FROM history
),
base AS (
  SELECT
    equipment_id,
    timestamp_utc,
    CAST(CASE
      WHEN rh IS NULL OR vav_discharge_t IS NULL OR vav_inlet_t IS NULL THEN 0
      WHEN COALESCE(zone_flow, 0) > {{FLOW_ON_MIN}}
       AND rh > {{REHEAT_CMD}}
       AND (vav_discharge_t - vav_inlet_t) < {{MIN_RISE}} THEN 1
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
