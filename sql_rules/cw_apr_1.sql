-- cw_apr_1.sql — High CW approach at full tower fan
WITH h AS (
  SELECT
    equipment_id,
    timestamp_utc,
    cw_supply_t, web_wb_t,
    CASE WHEN tower_fan_cmd IS NULL THEN NULL WHEN tower_fan_cmd > 1.0 THEN tower_fan_cmd / 100.0 ELSE tower_fan_cmd END AS fan,
    pump_status,
    chiller_status,
    chw_flow,
    chw_pump_cmd,
    CASE
      WHEN pump_status IS NOT NULL THEN CASE WHEN pump_status > 0.05 THEN 1 ELSE 0 END
      WHEN chiller_status IS NOT NULL THEN CASE WHEN chiller_status > 0.05 THEN 1 ELSE 0 END
      WHEN chw_flow IS NOT NULL THEN CASE WHEN chw_flow > 1.0 THEN 1 ELSE 0 END
      WHEN chw_pump_cmd IS NOT NULL THEN CASE WHEN (CASE WHEN chw_pump_cmd > 1.0 THEN chw_pump_cmd / 100.0 ELSE chw_pump_cmd END) > 0.05 THEN 1 ELSE 0 END
      ELSE 0
    END AS proof_on

  FROM history
),
base AS (
  SELECT
    equipment_id,
    timestamp_utc,
    CAST(CASE
      WHEN COALESCE(proof_on, 0) = 0 THEN 0
      WHEN cw_supply_t IS NULL OR web_wb_t IS NULL OR fan IS NULL THEN 0
      WHEN fan >= {{TOWER_FAN_HI}}
       AND (cw_supply_t - web_wb_t) > {{APPROACH_MAX_F}} THEN 1
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
