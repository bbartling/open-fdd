-- PostgreSQL adaptation. Render numeric template parameters with render_rule.py.
-- Inputs must be scoped to one tenant/site and cadence; see README.md.
-- sv_flatline.sql — Sensor flatline (stuck) — pandas FLATLINE_SENSOR_ROLES catalog
-- Temperature/humidity analogs (SENSOR_LIMITS minus duct static). Faults when ANY
-- mapped role is flat while the equipment is energized.
-- {{FLATLINE_ROWS}} / {{FLATLINE_ROWS_PRECEDING}} are derived from FLATLINE_HOURS
-- and POLL_SECONDS (DataFusion requires literal ROWS frame bounds).
WITH h AS (
  SELECT
    equipment_id,
    timestamp_utc,
    oa_t, mat, zone_t, rat, sat,
    chw_supply_t, chw_return_t, hw_supply_t, hw_return_t, oa_h,
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
      - MIN(sat) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS BETWEEN {{FLATLINE_ROWS_PRECEDING}} PRECEDING AND CURRENT ROW) AS span_sat,
    COUNT(chw_supply_t) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS BETWEEN {{FLATLINE_ROWS_PRECEDING}} PRECEDING AND CURRENT ROW) AS n_chw_supply_t,
    MAX(chw_supply_t) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS BETWEEN {{FLATLINE_ROWS_PRECEDING}} PRECEDING AND CURRENT ROW)
      - MIN(chw_supply_t) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS BETWEEN {{FLATLINE_ROWS_PRECEDING}} PRECEDING AND CURRENT ROW) AS span_chw_supply_t,
    COUNT(chw_return_t) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS BETWEEN {{FLATLINE_ROWS_PRECEDING}} PRECEDING AND CURRENT ROW) AS n_chw_return_t,
    MAX(chw_return_t) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS BETWEEN {{FLATLINE_ROWS_PRECEDING}} PRECEDING AND CURRENT ROW)
      - MIN(chw_return_t) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS BETWEEN {{FLATLINE_ROWS_PRECEDING}} PRECEDING AND CURRENT ROW) AS span_chw_return_t,
    COUNT(hw_supply_t) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS BETWEEN {{FLATLINE_ROWS_PRECEDING}} PRECEDING AND CURRENT ROW) AS n_hw_supply_t,
    MAX(hw_supply_t) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS BETWEEN {{FLATLINE_ROWS_PRECEDING}} PRECEDING AND CURRENT ROW)
      - MIN(hw_supply_t) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS BETWEEN {{FLATLINE_ROWS_PRECEDING}} PRECEDING AND CURRENT ROW) AS span_hw_supply_t,
    COUNT(hw_return_t) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS BETWEEN {{FLATLINE_ROWS_PRECEDING}} PRECEDING AND CURRENT ROW) AS n_hw_return_t,
    MAX(hw_return_t) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS BETWEEN {{FLATLINE_ROWS_PRECEDING}} PRECEDING AND CURRENT ROW)
      - MIN(hw_return_t) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS BETWEEN {{FLATLINE_ROWS_PRECEDING}} PRECEDING AND CURRENT ROW) AS span_hw_return_t,
    COUNT(oa_h) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS BETWEEN {{FLATLINE_ROWS_PRECEDING}} PRECEDING AND CURRENT ROW) AS n_oa_h,
    MAX(oa_h) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS BETWEEN {{FLATLINE_ROWS_PRECEDING}} PRECEDING AND CURRENT ROW)
      - MIN(oa_h) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS BETWEEN {{FLATLINE_ROWS_PRECEDING}} PRECEDING AND CURRENT ROW) AS span_oa_h
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
      WHEN n_chw_supply_t >= {{FLATLINE_ROWS}} AND span_chw_supply_t <= {{FLATLINE_TOL}} THEN 1
      WHEN n_chw_return_t >= {{FLATLINE_ROWS}} AND span_chw_return_t <= {{FLATLINE_TOL}} THEN 1
      WHEN n_hw_supply_t >= {{FLATLINE_ROWS}} AND span_hw_supply_t <= {{FLATLINE_TOL}} THEN 1
      WHEN n_hw_return_t >= {{FLATLINE_ROWS}} AND span_hw_return_t <= {{FLATLINE_TOL}} THEN 1
      WHEN n_oa_h >= {{FLATLINE_ROWS}} AND span_oa_h <= {{FLATLINE_TOL}} THEN 1
      ELSE 0
    END AS INT) AS raw_fault
  FROM win
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
