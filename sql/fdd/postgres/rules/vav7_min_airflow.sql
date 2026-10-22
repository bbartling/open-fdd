-- PostgreSQL adaptation. Render numeric template parameters with render_rule.py.
-- Inputs must be scoped to one tenant/site and cadence; see README.md.
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
elapsed_hold AS (
  -- Forward sample-and-hold. A gap longer than MAX_GAP_HOURS is unknown:
  -- it is not fault time, not covered time, and it breaks confirmation.
  -- The last sample has no forward interval.
  SELECT
    stepped.*,
    CASE
      WHEN stepped.dt_seconds IS NULL
        OR stepped.dt_seconds <= 0.0
        OR stepped.dt_seconds > ({{MAX_GAP_HOURS}} * 3600.0)
      THEN 0.0
      ELSE stepped.dt_seconds
    END AS held_seconds,
    CASE
      WHEN stepped.dt_seconds > ({{MAX_GAP_HOURS}} * 3600.0) THEN 1
      ELSE 0
    END AS gap_after
  FROM (
    SELECT
      src.*,
      EXTRACT(EPOCH FROM (
        LEAD(src.timestamp_utc) OVER (
          PARTITION BY src.equipment_id ORDER BY src.timestamp_utc
        ) - src.timestamp_utc
      )) AS dt_seconds
    FROM base src
  ) stepped
),
lagged AS (
  SELECT
    *,
    CASE
      WHEN raw_fault = LAG(raw_fault) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc)
       AND COALESCE(LAG(gap_after) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc), 0) = 0
      THEN 0 ELSE 1
    END AS is_new_streak
  FROM elapsed_hold
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
    SUM(held_seconds) OVER (
      PARTITION BY equipment_id, streak_id ORDER BY timestamp_utc
      ROWS UNBOUNDED PRECEDING
    ) AS streak_elapsed
  FROM grp
),
final AS (
  SELECT
    equipment_id,
    held_seconds,
    CASE WHEN raw_fault = 1 AND streak_elapsed >= {{CONFIRM_SECONDS}} THEN 1 ELSE 0 END AS confirmed
  FROM ranked
)
SELECT
  equipment_id,
  SUM(CASE WHEN confirmed = 1 THEN held_seconds ELSE 0.0 END) / 3600.0 AS fault_hours,
  SUM(held_seconds) / 3600.0 AS covered_hours,
  100.0 * SUM(CASE WHEN confirmed = 1 THEN held_seconds ELSE 0.0 END) / NULLIF(SUM(held_seconds), 0.0) AS fault_pct
FROM final
GROUP BY equipment_id;
