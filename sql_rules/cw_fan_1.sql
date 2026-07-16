-- cw_fan_1.sql — Excess tower fan energy vs wet-bulb limit
WITH h AS (
  SELECT
    equipment_id,
    timestamp_utc,
    cw_supply_t, web_wb_t,
    CASE WHEN tower_fan_cmd IS NULL THEN NULL WHEN tower_fan_cmd > 1.0 THEN tower_fan_cmd / 100.0 ELSE tower_fan_cmd END AS fan
  FROM history
),
base AS (
  SELECT
    equipment_id,
    timestamp_utc,
    CAST(CASE
      WHEN cw_supply_t IS NULL OR web_wb_t IS NULL OR fan IS NULL THEN 0
      WHEN fan >= {{TOWER_FAN_HI}}
       AND cw_supply_t > web_wb_t + {{CW_APPROACH}} + {{EXCESS_BEYOND_APPROACH_F}} THEN 1
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
