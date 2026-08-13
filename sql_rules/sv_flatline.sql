-- sv_flatline.sql — Sensor flatline (stuck) — portable multi-role sweep
-- Temperature/humidity analogs only (matches pandas FLATLINE_SENSOR_ROLES).
-- Rolling window: a role is flat when (MAX - MIN) over the last FLATLINE_HOURS
-- of samples stays within FLATLINE_TOL. Faults when ANY mapped role is flat
-- while the equipment is energized. {{FLATLINE_ROWS}} / {{FLATLINE_ROWS_PRECEDING}}
-- are derived from FLATLINE_HOURS and POLL_SECONDS (DataFusion requires literal
-- ROWS frame bounds).
WITH h AS (
  SELECT
    equipment_id,
    timestamp_utc,
    oa_t, mat, zone_t, rat, sat,
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
win AS (
  SELECT
    equipment_id,
    timestamp_utc,
    energized,
    COUNT(oa_t) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS BETWEEN {{FLATLINE_ROWS_PRECEDING}} PRECEDING AND CURRENT ROW) AS n_oa_t,
    MAX(oa_t) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS BETWEEN {{FLATLINE_ROWS_PRECEDING}} PRECEDING AND CURRENT ROW)
      - MIN(oa_t) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS BETWEEN {{FLATLINE_ROWS_PRECEDING}} PRECEDING AND CURRENT ROW) AS span_oa_t,
    COUNT(mat) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS BETWEEN {{FLATLINE_ROWS_PRECEDING}} PRECEDING AND CURRENT ROW) AS n_mat,
    MAX(mat) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS BETWEEN {{FLATLINE_ROWS_PRECEDING}} PRECEDING AND CURRENT ROW)
      - MIN(mat) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS BETWEEN {{FLATLINE_ROWS_PRECEDING}} PRECEDING AND CURRENT ROW) AS span_mat,
    COUNT(zone_t) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS BETWEEN {{FLATLINE_ROWS_PRECEDING}} PRECEDING AND CURRENT ROW) AS n_zone_t,
    MAX(zone_t) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS BETWEEN {{FLATLINE_ROWS_PRECEDING}} PRECEDING AND CURRENT ROW)
      - MIN(zone_t) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS BETWEEN {{FLATLINE_ROWS_PRECEDING}} PRECEDING AND CURRENT ROW) AS span_zone_t,
    COUNT(rat) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS BETWEEN {{FLATLINE_ROWS_PRECEDING}} PRECEDING AND CURRENT ROW) AS n_rat,
    MAX(rat) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS BETWEEN {{FLATLINE_ROWS_PRECEDING}} PRECEDING AND CURRENT ROW)
      - MIN(rat) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS BETWEEN {{FLATLINE_ROWS_PRECEDING}} PRECEDING AND CURRENT ROW) AS span_rat,
    COUNT(sat) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS BETWEEN {{FLATLINE_ROWS_PRECEDING}} PRECEDING AND CURRENT ROW) AS n_sat,
    MAX(sat) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS BETWEEN {{FLATLINE_ROWS_PRECEDING}} PRECEDING AND CURRENT ROW)
      - MIN(sat) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS BETWEEN {{FLATLINE_ROWS_PRECEDING}} PRECEDING AND CURRENT ROW) AS span_sat
  FROM h
),
base AS (
  SELECT
    equipment_id,
    timestamp_utc,
    CAST(CASE
      WHEN COALESCE(energized, 0) = 0 THEN 0
      WHEN n_oa_t >= {{FLATLINE_ROWS}} AND span_oa_t <= {{FLATLINE_TOL}} THEN 1
      WHEN n_mat >= {{FLATLINE_ROWS}} AND span_mat <= {{FLATLINE_TOL}} THEN 1
      WHEN n_zone_t >= {{FLATLINE_ROWS}} AND span_zone_t <= {{FLATLINE_TOL}} THEN 1
      WHEN n_rat >= {{FLATLINE_ROWS}} AND span_rat <= {{FLATLINE_TOL}} THEN 1
      WHEN n_sat >= {{FLATLINE_ROWS}} AND span_sat <= {{FLATLINE_TOL}} THEN 1
      ELSE 0
    END AS INT) AS raw_fault
  FROM win
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
