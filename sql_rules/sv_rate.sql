-- sv_rate.sql — Context-aware sensor rate of change (portable channels)
-- Rate is normalized to °F/h so the threshold is poll-interval independent, and
-- the exceedance must be *sustained* (two consecutive samples) to separate a
-- slew from a one-sample SV-SPIKE. Samples separated by more than
-- PERSISTENCE_MIN are treated as a data gap, not a slew.
WITH h AS (
  SELECT
    equipment_id,
    timestamp_utc,
    oa_t, mat, zone_t, rat, sat,
    LAG(oa_t) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc) AS prev_oa_t,
    LAG(mat) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc) AS prev_mat,
    LAG(zone_t) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc) AS prev_zone_t,
    LAG(rat) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc) AS prev_rat,
    LAG(sat) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc) AS prev_sat,
    LAG(timestamp_utc) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc) AS prev_ts
  FROM history
),
rates AS (
  SELECT
    equipment_id,
    timestamp_utc,
    CAST(EXTRACT(EPOCH FROM (timestamp_utc - prev_ts)) AS DOUBLE) / 3600.0 AS dt_hours,
    oa_t - prev_oa_t AS d_oa_t,
    mat - prev_mat AS d_mat,
    zone_t - prev_zone_t AS d_zone_t,
    rat - prev_rat AS d_rat,
    sat - prev_sat AS d_sat,
    prev_ts
  FROM h
),
flagged AS (
  SELECT
    equipment_id,
    timestamp_utc,
    CAST(CASE
      WHEN prev_ts IS NULL THEN 0
      WHEN CAST(EXTRACT(EPOCH FROM (timestamp_utc - prev_ts)) AS DOUBLE) > {{PERSISTENCE_MIN}} * 60.0 THEN 0
      WHEN dt_hours IS NULL OR dt_hours <= 0.0 THEN 0
      WHEN ABS(d_oa_t) / dt_hours > {{STEADY_FAULT_PER_HOUR}} THEN 1
      WHEN ABS(d_mat) / dt_hours > {{STEADY_FAULT_PER_HOUR}} THEN 1
      WHEN ABS(d_zone_t) / dt_hours > {{STEADY_FAULT_PER_HOUR}} THEN 1
      WHEN ABS(d_rat) / dt_hours > {{STEADY_FAULT_PER_HOUR}} THEN 1
      WHEN ABS(d_sat) / dt_hours > {{STEADY_FAULT_PER_HOUR}} THEN 1
      ELSE 0
    END AS INT) AS over_rate
  FROM rates
),
base AS (
  SELECT
    equipment_id,
    timestamp_utc,
    CAST(CASE
      WHEN over_rate = 1
       AND COALESCE(LAG(over_rate) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc), 0) = 1
      THEN 1 ELSE 0
    END AS INT) AS raw_fault
  FROM flagged
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
