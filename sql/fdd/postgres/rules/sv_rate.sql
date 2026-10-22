-- PostgreSQL adaptation. Render numeric template parameters with render_rule.py.
-- Inputs must be scoped to one tenant/site and cadence; see README.md.
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
    CAST(EXTRACT(EPOCH FROM (timestamp_utc - prev_ts)) AS DOUBLE PRECISION) / 3600.0 AS dt_hours,
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
      WHEN CAST(EXTRACT(EPOCH FROM (timestamp_utc - prev_ts)) AS DOUBLE PRECISION) > {{MAX_GAP_HOURS}} * 3600.0 THEN 0
      WHEN dt_hours IS NULL OR dt_hours <= 0.0 THEN 0
      WHEN ABS(d_oa_t) / dt_hours > ({{STEADY_FAULT_PER_HOUR}} * {{SENSOR_SPAN}} / 100.0) THEN 1
      WHEN ABS(d_mat) / dt_hours > ({{STEADY_FAULT_PER_HOUR}} * {{SENSOR_SPAN}} / 100.0) THEN 1
      WHEN ABS(d_zone_t) / dt_hours > ({{STEADY_FAULT_PER_HOUR}} * {{SENSOR_SPAN}} / 100.0) THEN 1
      WHEN ABS(d_rat) / dt_hours > ({{STEADY_FAULT_PER_HOUR}} * {{SENSOR_SPAN}} / 100.0) THEN 1
      WHEN ABS(d_sat) / dt_hours > ({{STEADY_FAULT_PER_HOUR}} * {{SENSOR_SPAN}} / 100.0) THEN 1
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
