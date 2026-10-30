-- PostgreSQL adaptation. Render numeric template parameters with render_rule.py.
-- Inputs must be scoped to one tenant/site and cadence; see README.md.
-- sv_spike.sql — Sensor rate-of-change spike — pandas SENSOR_LIMITS catalog
-- Storage is SI (metric-c-v2): temperature spike limits are K (delta °C), duct static Pa, humidity percent RH.
-- Per-role spike limits (scaled by SPIKE_SCALE). Humidity/pressure included.
WITH h AS (
  SELECT
    equipment_id,
    timestamp_utc,
    oa_t, mat, zone_t, rat, sat,
    chw_supply_t, chw_return_t, hw_supply_t, hw_return_t, oa_h, duct_static,
    LAG(oa_t) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc) AS prev_oa_t,
    LAG(mat) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc) AS prev_mat,
    LAG(zone_t) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc) AS prev_zone_t,
    LAG(rat) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc) AS prev_rat,
    LAG(sat) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc) AS prev_sat,
    LAG(chw_supply_t) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc) AS prev_chw_supply_t,
    LAG(chw_return_t) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc) AS prev_chw_return_t,
    LAG(hw_supply_t) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc) AS prev_hw_supply_t,
    LAG(hw_return_t) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc) AS prev_hw_return_t,
    LAG(oa_h) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc) AS prev_oa_h,
    LAG(duct_static) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc) AS prev_duct_static,
    fan_cmd, fan_status, pump_status, chw_pump_cmd, chiller_status, zone_flow,
    CASE
      WHEN fan_status IS NOT NULL THEN CASE WHEN fan_status > 0.05 THEN 1 ELSE 0 END
      WHEN fan_cmd IS NOT NULL THEN CASE WHEN (CASE WHEN fan_cmd > 1.0 THEN fan_cmd / 100.0 ELSE fan_cmd END) > 0.01 THEN 1 ELSE 0 END
      -- VAV airflow proxy (operational_gate.resolve_fan_running): 50 cfm = 23.597350 L/s SI.
      WHEN zone_flow IS NOT NULL THEN CASE WHEN zone_flow > 23.597350 THEN 1 ELSE 0 END
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
      WHEN {{REQUIRE_OPERATIONAL_GATE}} >= 0.5 AND COALESCE(energized, 0) = 0 THEN 0
      WHEN oa_t IS NOT NULL AND prev_oa_t IS NOT NULL AND ABS(oa_t - prev_oa_t) > 20.000000 * {{SPIKE_SCALE_TEMPERATURE}} THEN 1
      WHEN mat IS NOT NULL AND prev_mat IS NOT NULL AND ABS(mat - prev_mat) > 13.888889 * {{SPIKE_SCALE_TEMPERATURE}} THEN 1
      WHEN zone_t IS NOT NULL AND prev_zone_t IS NOT NULL AND ABS(zone_t - prev_zone_t) > 6.666667 * {{SPIKE_SCALE_TEMPERATURE}} THEN 1
      WHEN rat IS NOT NULL AND prev_rat IS NOT NULL AND ABS(rat - prev_rat) > 6.666667 * {{SPIKE_SCALE_TEMPERATURE}} THEN 1
      WHEN sat IS NOT NULL AND prev_sat IS NOT NULL AND ABS(sat - prev_sat) > 22.222222 * {{SPIKE_SCALE_TEMPERATURE}} THEN 1
      WHEN chw_supply_t IS NOT NULL AND prev_chw_supply_t IS NOT NULL AND ABS(chw_supply_t - prev_chw_supply_t) > 11.111111 * {{SPIKE_SCALE_TEMPERATURE}} THEN 1
      WHEN chw_return_t IS NOT NULL AND prev_chw_return_t IS NOT NULL AND ABS(chw_return_t - prev_chw_return_t) > 11.111111 * {{SPIKE_SCALE_TEMPERATURE}} THEN 1
      WHEN hw_supply_t IS NOT NULL AND prev_hw_supply_t IS NOT NULL AND ABS(hw_supply_t - prev_hw_supply_t) > 33.333333 * {{SPIKE_SCALE_TEMPERATURE}} THEN 1
      WHEN hw_return_t IS NOT NULL AND prev_hw_return_t IS NOT NULL AND ABS(hw_return_t - prev_hw_return_t) > 33.333333 * {{SPIKE_SCALE_TEMPERATURE}} THEN 1
      WHEN oa_h IS NOT NULL AND prev_oa_h IS NOT NULL AND ABS(oa_h - prev_oa_h) > 25.0 * {{SPIKE_SCALE_HUMIDITY}} THEN 1
      WHEN duct_static IS NOT NULL AND prev_duct_static IS NOT NULL AND ABS(duct_static - prev_duct_static) > 497.68 * {{SPIKE_SCALE_PRESSURE}} THEN 1
      ELSE 0
    END AS INT) AS raw_fault
  FROM h
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
, cov AS (
  SELECT equipment_id,
    100.0 * AVG(CAST(COALESCE(energized, 1) AS DOUBLE PRECISION)) AS cov_pct
  FROM h
  GROUP BY equipment_id
)
SELECT
  f.equipment_id,
  CASE
    WHEN {{REQUIRE_OPERATIONAL_GATE}} < 0.5 THEN SUM(CASE WHEN f.confirmed = 1 THEN f.held_seconds ELSE 0.0 END) / 3600.0
    WHEN MAX(c.cov_pct) < {{MINIMUM_ACTIVE_COVERAGE_PCT}} THEN 0.0
    ELSE SUM(CASE WHEN f.confirmed = 1 THEN f.held_seconds ELSE 0.0 END) / 3600.0
  END AS fault_hours,
  SUM(f.held_seconds) / 3600.0 AS covered_hours,
  CASE
    WHEN {{REQUIRE_OPERATIONAL_GATE}} < 0.5 THEN 100.0 * SUM(CASE WHEN f.confirmed = 1 THEN f.held_seconds ELSE 0.0 END) / NULLIF(SUM(f.held_seconds), 0.0)
    WHEN MAX(c.cov_pct) < {{MINIMUM_ACTIVE_COVERAGE_PCT}} THEN 0.0
    ELSE 100.0 * SUM(CASE WHEN f.confirmed = 1 THEN f.held_seconds ELSE 0.0 END) / NULLIF(SUM(f.held_seconds), 0.0)
  END AS fault_pct
FROM final f
LEFT JOIN cov c ON f.equipment_id = c.equipment_id
GROUP BY f.equipment_id;
