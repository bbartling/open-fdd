-- PostgreSQL adaptation. Render numeric template parameters with render_rule.py.
-- Inputs must be scoped to one tenant/site and cadence; see README.md.
-- sv_range.sql — Sensor out of hard range (pandas SENSOR_LIMITS catalog)
-- Do not force everything through oa_t. Humidity/pressure are not temperature-scaled.
-- Points without a declared binding unit are masked (not assessed), matching pandas sweep_assessable_role.
WITH bind AS (
  SELECT
    MAX(a.unit) FILTER (WHERE a.role = 'oa_t') AS u_oa_t,
    MAX(a.unit) FILTER (WHERE a.role = 'mat') AS u_mat,
    MAX(a.unit) FILTER (WHERE a.role = 'zone_t') AS u_zone_t,
    MAX(a.unit) FILTER (WHERE a.role = 'rat') AS u_rat,
    MAX(a.unit) FILTER (WHERE a.role = 'sat') AS u_sat,
    MAX(a.unit) FILTER (WHERE a.role = 'chw_supply_t') AS u_chw_supply_t,
    MAX(a.unit) FILTER (WHERE a.role = 'chw_return_t') AS u_chw_return_t,
    MAX(a.unit) FILTER (WHERE a.role = 'hw_supply_t') AS u_hw_supply_t,
    MAX(a.unit) FILTER (WHERE a.role = 'hw_return_t') AS u_hw_return_t,
    MAX(a.unit) FILTER (WHERE a.role = 'oa_h') AS u_oa_h,
    MAX(a.unit) FILTER (WHERE a.role = 'ra_h') AS u_ra_h,
    MAX(a.unit) FILTER (WHERE a.role = 'zone_rh') AS u_zone_rh,
    MAX(a.unit) FILTER (WHERE a.role = 'ma_h') AS u_ma_h,
    MAX(a.unit) FILTER (WHERE a.role = 'sa_h') AS u_sa_h,
    MAX(a.unit) FILTER (WHERE a.role = 'duct_static') AS u_duct_static
  FROM authorized_series a
  JOIN equipment e ON e.building_id = a.site_id AND e.equipment_id = a.equipment_id
  WHERE e.equipment_id = (SELECT MIN(equipment_id) FROM history)
    AND (SELECT count(*)::int FROM authorized_series c
         WHERE c.site_id = a.site_id AND c.equipment_id = a.equipment_id AND c.role = a.role) = 1
),
gated AS (
  SELECT
    h.equipment_id,
    h.timestamp_utc,
    fdd.mask_sweep_val('oa_t', b.u_oa_t, h.oa_t) AS oa_t,
    fdd.mask_sweep_val('mat', b.u_mat, h.mat) AS mat,
    fdd.mask_sweep_val('zone_t', b.u_zone_t, h.zone_t) AS zone_t,
    fdd.mask_sweep_val('rat', b.u_rat, h.rat) AS rat,
    fdd.mask_sweep_val('sat', b.u_sat, h.sat) AS sat,
    fdd.mask_sweep_val('chw_supply_t', b.u_chw_supply_t, h.chw_supply_t) AS chw_supply_t,
    fdd.mask_sweep_val('chw_return_t', b.u_chw_return_t, h.chw_return_t) AS chw_return_t,
    fdd.mask_sweep_val('hw_supply_t', b.u_hw_supply_t, h.hw_supply_t) AS hw_supply_t,
    fdd.mask_sweep_val('hw_return_t', b.u_hw_return_t, h.hw_return_t) AS hw_return_t,
    fdd.mask_sweep_val('oa_h', b.u_oa_h, h.oa_h) AS oa_h,
    fdd.mask_sweep_val('ra_h', b.u_ra_h, h.ra_h) AS ra_h,
    fdd.mask_sweep_val('zone_rh', b.u_zone_rh, h.zone_rh) AS zone_rh,
    fdd.mask_sweep_val('ma_h', b.u_ma_h, h.ma_h) AS ma_h,
    fdd.mask_sweep_val('sa_h', b.u_sa_h, h.sa_h) AS sa_h,
    fdd.mask_sweep_val('duct_static', b.u_duct_static, h.duct_static) AS duct_static,
    h.fan_cmd,
    h.fan_status,
    h.pump_status,
    h.chw_pump_cmd,
    h.chiller_status
  FROM history h
  CROSS JOIN bind b
),
h AS (
  SELECT
    equipment_id,
    timestamp_utc,
    oa_t, mat, zone_t, rat, sat,
    chw_supply_t, chw_return_t, hw_supply_t, hw_return_t,
    oa_h, ra_h, zone_rh, ma_h, sa_h, duct_static,
    fan_cmd, fan_status, pump_status, chw_pump_cmd, chiller_status,
    CASE
      WHEN fan_status IS NOT NULL THEN CASE WHEN fan_status > 0.05 THEN 1 ELSE 0 END
      WHEN fan_cmd IS NOT NULL THEN CASE WHEN (CASE WHEN fan_cmd > 1.0 THEN fan_cmd / 100.0 ELSE fan_cmd END) > 0.01 THEN 1 ELSE 0 END
      WHEN pump_status IS NOT NULL THEN CASE WHEN pump_status > 0.05 THEN 1 ELSE 0 END
      WHEN chw_pump_cmd IS NOT NULL THEN CASE WHEN (CASE WHEN chw_pump_cmd > 1.0 THEN chw_pump_cmd / 100.0 ELSE chw_pump_cmd END) > 0.05 THEN 1 ELSE 0 END
      WHEN chiller_status IS NOT NULL THEN CASE WHEN chiller_status > 0.05 THEN 1 ELSE 0 END
      ELSE 1
    END AS energized
  FROM gated
),
base AS (
  SELECT
    equipment_id,
    timestamp_utc,
    CAST(CASE
      WHEN COALESCE(energized, 0) = 0 THEN 0
      WHEN oa_t IS NOT NULL AND (oa_t = CAST('NaN' AS DOUBLE PRECISION) OR oa_t < -60.0 * {{RANGE_SCALE_TEMPERATURE}} OR oa_t > 130.0 * {{RANGE_SCALE_TEMPERATURE}}) THEN 1
      WHEN mat IS NOT NULL AND (mat = CAST('NaN' AS DOUBLE PRECISION) OR mat < -20.0 * {{RANGE_SCALE_TEMPERATURE}} OR mat > 110.0 * {{RANGE_SCALE_TEMPERATURE}}) THEN 1
      WHEN zone_t IS NOT NULL AND (zone_t = CAST('NaN' AS DOUBLE PRECISION) OR zone_t < 40.0 * {{RANGE_SCALE_TEMPERATURE}} OR zone_t > 100.0 * {{RANGE_SCALE_TEMPERATURE}}) THEN 1
      WHEN rat IS NOT NULL AND (rat = CAST('NaN' AS DOUBLE PRECISION) OR rat < 40.0 * {{RANGE_SCALE_TEMPERATURE}} OR rat > 100.0 * {{RANGE_SCALE_TEMPERATURE}}) THEN 1
      WHEN sat IS NOT NULL AND (sat = CAST('NaN' AS DOUBLE PRECISION) OR sat < 30.0 * {{RANGE_SCALE_TEMPERATURE}} OR sat > 150.0 * {{RANGE_SCALE_TEMPERATURE}}) THEN 1
      WHEN chw_supply_t IS NOT NULL AND (chw_supply_t = CAST('NaN' AS DOUBLE PRECISION) OR chw_supply_t < 30.0 * {{RANGE_SCALE_TEMPERATURE}} OR chw_supply_t > 80.0 * {{RANGE_SCALE_TEMPERATURE}}) THEN 1
      WHEN chw_return_t IS NOT NULL AND (chw_return_t = CAST('NaN' AS DOUBLE PRECISION) OR chw_return_t < 30.0 * {{RANGE_SCALE_TEMPERATURE}} OR chw_return_t > 90.0 * {{RANGE_SCALE_TEMPERATURE}}) THEN 1
      WHEN hw_supply_t IS NOT NULL AND (hw_supply_t = CAST('NaN' AS DOUBLE PRECISION) OR hw_supply_t < 40.0 * {{RANGE_SCALE_TEMPERATURE}} OR hw_supply_t > 220.0 * {{RANGE_SCALE_TEMPERATURE}}) THEN 1
      WHEN hw_return_t IS NOT NULL AND (hw_return_t = CAST('NaN' AS DOUBLE PRECISION) OR hw_return_t < 40.0 * {{RANGE_SCALE_TEMPERATURE}} OR hw_return_t > 220.0 * {{RANGE_SCALE_TEMPERATURE}}) THEN 1
      WHEN oa_h IS NOT NULL AND (oa_h = CAST('NaN' AS DOUBLE PRECISION) OR oa_h < 0.0 * {{RANGE_SCALE_HUMIDITY}} OR oa_h > 100.0 * {{RANGE_SCALE_HUMIDITY}}) THEN 1
      WHEN ra_h IS NOT NULL AND (ra_h = CAST('NaN' AS DOUBLE PRECISION) OR ra_h < 0.0 * {{RANGE_SCALE_HUMIDITY}} OR ra_h > 100.0 * {{RANGE_SCALE_HUMIDITY}}) THEN 1
      WHEN zone_rh IS NOT NULL AND (zone_rh = CAST('NaN' AS DOUBLE PRECISION) OR zone_rh < 0.0 * {{RANGE_SCALE_HUMIDITY}} OR zone_rh > 100.0 * {{RANGE_SCALE_HUMIDITY}}) THEN 1
      WHEN ma_h IS NOT NULL AND (ma_h = CAST('NaN' AS DOUBLE PRECISION) OR ma_h < 0.0 * {{RANGE_SCALE_HUMIDITY}} OR ma_h > 100.0 * {{RANGE_SCALE_HUMIDITY}}) THEN 1
      WHEN sa_h IS NOT NULL AND (sa_h = CAST('NaN' AS DOUBLE PRECISION) OR sa_h < 0.0 * {{RANGE_SCALE_HUMIDITY}} OR sa_h > 100.0 * {{RANGE_SCALE_HUMIDITY}}) THEN 1
      WHEN duct_static IS NOT NULL AND (duct_static = CAST('NaN' AS DOUBLE PRECISION) OR duct_static < -1.0 * {{RANGE_SCALE_PRESSURE}} OR duct_static > 8.0 * {{RANGE_SCALE_PRESSURE}}) THEN 1
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
SELECT
  equipment_id,
  SUM(CASE WHEN confirmed = 1 THEN held_seconds ELSE 0.0 END) / 3600.0 AS fault_hours,
  SUM(held_seconds) / 3600.0 AS covered_hours,
  100.0 * SUM(CASE WHEN confirmed = 1 THEN held_seconds ELSE 0.0 END) / NULLIF(SUM(held_seconds), 0.0) AS fault_pct
FROM final
GROUP BY equipment_id;
