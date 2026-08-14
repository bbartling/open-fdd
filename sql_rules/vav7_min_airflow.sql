-- vav7_min_airflow.sql — three pandas branches: under-min, fixed-high flow, high min SP.
-- Rolling windows use poll-derived {{FIXED_FLOW_ROWS}} (1h sample count), matching pandas.
WITH h AS (
  SELECT
    equipment_id,
    timestamp_utc,
    zone_flow,
    min_flow_sp,
    fan_cmd,
    fan_status,
    CASE
      WHEN fan_status IS NOT NULL THEN CASE WHEN fan_status > 0.05 THEN 1 ELSE 0 END
      WHEN fan_cmd IS NOT NULL THEN CASE WHEN (CASE WHEN fan_cmd > 1.0 THEN fan_cmd / 100.0 ELSE fan_cmd END) > 0.01 THEN 1 ELSE 0 END
      WHEN zone_flow IS NOT NULL AND zone_flow > {{FLOW_ON_MIN}} THEN 1
      ELSE 1
    END AS fan_on
  FROM history
),
rolled AS (
  SELECT
    *,
    STDDEV_SAMP(zone_flow) OVER (
      PARTITION BY equipment_id ORDER BY timestamp_utc
      ROWS BETWEEN {{FIXED_FLOW_ROWS_PRECEDING}} PRECEDING AND CURRENT ROW
    ) AS roll_std,
    AVG(zone_flow) OVER (
      PARTITION BY equipment_id ORDER BY timestamp_utc
      ROWS BETWEEN {{FIXED_FLOW_ROWS_PRECEDING}} PRECEDING AND CURRENT ROW
    ) AS roll_mean,
    COUNT(zone_flow) OVER (
      PARTITION BY equipment_id ORDER BY timestamp_utc
      ROWS BETWEEN {{FIXED_FLOW_ROWS_PRECEDING}} PRECEDING AND CURRENT ROW
    ) AS roll_n
  FROM h
),
base AS (
  SELECT
    equipment_id,
    timestamp_utc,
    CAST(CASE
      WHEN COALESCE(fan_on, 0) = 0 THEN 0
      WHEN zone_flow IS NULL THEN 0
      WHEN min_flow_sp IS NOT NULL AND zone_flow > {{FLOW_ON_MIN}} AND zone_flow < min_flow_sp THEN 1
      WHEN roll_n >= {{FIXED_FLOW_MIN_PERIODS}}
           AND zone_flow IS NOT NULL
           AND roll_std < {{FIXED_FLOW_MAX_STD}}
           AND roll_mean > {{FIXED_FLOW_MIN_MEAN}} THEN 1
      WHEN min_flow_sp IS NOT NULL
           AND roll_n >= {{FIXED_FLOW_MIN_PERIODS}}
           AND min_flow_sp > {{HIGH_MIN_FLOW_SP}}
           AND roll_std < {{FIXED_FLOW_MAX_STD}} THEN 1
      ELSE 0
    END AS INT) AS raw_fault
  FROM rolled
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
