-- sv_range.sql — Sensor out of hard range (OAT example; extend per sensor type)
WITH h AS (
  SELECT
    equipment_id,
    timestamp_utc,
    oa_t,
    fan_cmd,
    fan_status,
    pump_status,
    chw_pump_cmd,
    chiller_status,
    CASE
      WHEN fan_status IS NOT NULL THEN CASE WHEN fan_status > 0.05 THEN 1 ELSE 0 END
      WHEN fan_cmd IS NOT NULL THEN CASE WHEN (CASE WHEN fan_cmd > 1.0 THEN fan_cmd / 100.0 ELSE fan_cmd END) > 0.01 THEN 1 ELSE 0 END
      WHEN pump_status IS NOT NULL THEN CASE WHEN pump_status > 0.05 THEN 1 ELSE 0 END
      WHEN chw_pump_cmd IS NOT NULL THEN CASE WHEN (CASE WHEN chw_pump_cmd > 1.0 THEN chw_pump_cmd / 100.0 ELSE chw_pump_cmd END) > 0.05 THEN 1 ELSE 0 END
      WHEN chiller_status IS NOT NULL THEN CASE WHEN chiller_status > 0.05 THEN 1 ELSE 0 END
      ELSE 1
    END AS energized
  FROM history
),
base AS (
  SELECT
    equipment_id,
    timestamp_utc,
    CAST(CASE
      WHEN COALESCE(energized, 0) = 0 THEN 0
      WHEN oa_t IS NULL THEN 0
      WHEN oa_t < -60.0 * {{RANGE_SCALE_TEMPERATURE}} OR oa_t > 130.0 * {{RANGE_SCALE_TEMPERATURE}} THEN 1
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
