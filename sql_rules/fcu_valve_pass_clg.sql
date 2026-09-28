-- fcu_valve_pass_clg.sql — first-class FCU screening rule
WITH normalized AS (
  SELECT equipment_id, timestamp_utc, sat, zone_t, zone_co2,
    CASE WHEN htg_valve_pct IS NULL THEN NULL WHEN htg_valve_pct > 1.0 THEN htg_valve_pct / 100.0 ELSE htg_valve_pct END AS htg,
    CASE WHEN clg_valve_pct IS NULL THEN NULL WHEN clg_valve_pct > 1.0 THEN clg_valve_pct / 100.0 ELSE clg_valve_pct END AS clg,
    CASE WHEN damper_cmd IS NULL THEN NULL WHEN damper_cmd > 1.0 THEN damper_cmd / 100.0 ELSE damper_cmd END AS dcmd,
    CASE WHEN damper_pct IS NULL THEN NULL WHEN damper_pct > 1.0 THEN damper_pct / 100.0 ELSE damper_pct END AS dpos,
    CASE
      WHEN fan_status IS NOT NULL THEN CASE WHEN fan_status > 0.05 THEN 1 ELSE 0 END
      WHEN fan_cmd IS NOT NULL THEN CASE WHEN (CASE WHEN fan_cmd > 1.0 THEN fan_cmd / 100.0 ELSE fan_cmd END) > 0.10 THEN 1 ELSE 0 END
      ELSE 0
    END AS fan_on
  FROM history
), base AS (
  SELECT equipment_id, timestamp_utc,
    CAST(CASE WHEN sat IS NOT NULL AND zone_t IS NOT NULL AND fan_on = 1 AND htg <= 0.05 AND clg <= 0.05 AND zone_t - sat > {{PASS_DELTA_F}} THEN 1 ELSE 0 END AS INT) AS raw_fault
  FROM normalized
), lagged AS (
  SELECT *, CASE WHEN raw_fault = LAG(raw_fault) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc) THEN 0 ELSE 1 END AS is_new_streak
  FROM base
), grouped AS (
  SELECT *, SUM(is_new_streak) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS UNBOUNDED PRECEDING) AS streak_id
  FROM lagged
), ranked AS (
  SELECT *, ROW_NUMBER() OVER (PARTITION BY equipment_id, streak_id ORDER BY timestamp_utc) AS streak_len
  FROM grouped
)
SELECT equipment_id,
  SUM(CASE WHEN raw_fault = 1 AND streak_len >= {{CONFIRM_ROWS}} THEN 1 ELSE 0 END) * {{POLL_SECONDS}} / 3600.0 AS fault_hours
FROM ranked
GROUP BY equipment_id;

