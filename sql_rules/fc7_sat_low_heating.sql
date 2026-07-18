-- fc7_sat_low_heating.sql — FC7 SAT low while heating at full + confirm
WITH h AS (
  SELECT
    equipment_id,
    timestamp_utc,
    sat,
    sat_sp,
    COALESCE(CASE WHEN fan_cmd IS NULL THEN 0.0 WHEN fan_cmd > 1.0 THEN fan_cmd / 100.0 ELSE fan_cmd END, 0.0) AS fan,
    COALESCE(CASE WHEN htg_valve_pct IS NULL THEN NULL WHEN htg_valve_pct > 1.0 THEN htg_valve_pct / 100.0 ELSE htg_valve_pct END, 0.0) AS htg_valve_pct
  FROM history
),
base AS (
  SELECT
    equipment_id,
    timestamp_utc,
    CAST(CASE
      WHEN sat IS NOT NULL AND sat_sp IS NOT NULL AND fan > 0.01
       AND sat < sat_sp - {{SAT_ERR}} AND htg_valve_pct > {{HTG_FULL_MIN}}
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
