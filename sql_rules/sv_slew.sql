-- sv_slew.sql — SV-SLEW context-sensitive sustained rate (time-normalized)
-- Steady vs STARTUP_TRANSIENT thresholds; gap reject; zone extreme short-window.
-- Defaults from docs/rules/cookbook/sensor-rate-profiles.md / profiles YAML.
WITH h AS (
  SELECT * FROM history
),
w AS (
  SELECT
    equipment_id,
    timestamp_utc,
    oa_t,
    rat,
    mat,
    sat,
    zone_t,
    chw_supply_t,
    chw_return_t,
    hw_supply_t,
    hw_return_t,
    oa_h,
    duct_static,
    fan_status,
    to_unixtime(timestamp_utc) AS ts_epoch,
    LAG(to_unixtime(timestamp_utc)) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc) AS prev_epoch,
    LAG(oa_t) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc) AS prev_oa_t,
    LAG(rat) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc) AS prev_rat,
    LAG(mat) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc) AS prev_mat,
    LAG(sat) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc) AS prev_sat,
    LAG(zone_t) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc) AS prev_zone_t,
    LAG(chw_supply_t) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc) AS prev_chw_supply_t,
    LAG(chw_return_t) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc) AS prev_chw_return_t,
    LAG(hw_supply_t) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc) AS prev_hw_supply_t,
    LAG(hw_return_t) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc) AS prev_hw_return_t,
    LAG(oa_h) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc) AS prev_oa_h,
    LAG(duct_static) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc) AS prev_duct_static,
    CASE
      WHEN fan_status IS NULL THEN NULL
      WHEN TRIM(CAST(fan_status AS VARCHAR)) IN ('1', '1.0', 'true', 'TRUE', 'on', 'ON', 'yes', 'YES') THEN 1
      ELSE 0
    END AS fan_on_i
  FROM h
),
r AS (
  SELECT
    *,
    CASE
      WHEN prev_epoch IS NULL THEN NULL
      WHEN (ts_epoch - prev_epoch) <= 0 THEN NULL
      WHEN (ts_epoch - prev_epoch) > ({{POLL_SECONDS}} * {{MAX_GAP_FACTOR}}) THEN NULL
      ELSE CAST((ts_epoch - prev_epoch) AS DOUBLE)
    END AS dt_s,
    CASE
      WHEN fan_on_i IS NULL THEN 0
      WHEN fan_on_i = 1
        AND LAG(fan_on_i) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc) = 0
      THEN 1
      ELSE 0
    END AS fan_started
  FROM w
),
s AS (
  SELECT
    *,
    MAX(CASE WHEN fan_started = 1 THEN ts_epoch ELSE NULL END) OVER (
      PARTITION BY equipment_id
      ORDER BY timestamp_utc
      ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
    ) AS last_fan_start_epoch
  FROM r
),
rated AS (
  SELECT
    equipment_id,
    timestamp_utc,
    dt_s,
    CASE
      WHEN last_fan_start_epoch IS NOT NULL
        AND (ts_epoch - last_fan_start_epoch) >= 0
        AND (ts_epoch - last_fan_start_epoch) <= ({{FAN_TRANSIENT_MINUTES}} * 60.0)
      THEN TRUE
      ELSE FALSE
    END AS in_transient,
    CASE WHEN dt_s IS NOT NULL AND oa_t IS NOT NULL AND prev_oa_t IS NOT NULL
      THEN ABS(oa_t - prev_oa_t) / dt_s * 3600.0 ELSE NULL END AS oa_t_rate,
    CASE WHEN dt_s IS NOT NULL AND rat IS NOT NULL AND prev_rat IS NOT NULL
      THEN ABS(rat - prev_rat) / dt_s * 3600.0 ELSE NULL END AS rat_rate,
    CASE WHEN dt_s IS NOT NULL AND mat IS NOT NULL AND prev_mat IS NOT NULL
      THEN ABS(mat - prev_mat) / dt_s * 3600.0 ELSE NULL END AS mat_rate,
    CASE WHEN dt_s IS NOT NULL AND sat IS NOT NULL AND prev_sat IS NOT NULL
      THEN ABS(sat - prev_sat) / dt_s * 3600.0 ELSE NULL END AS sat_rate,
    CASE WHEN dt_s IS NOT NULL AND zone_t IS NOT NULL AND prev_zone_t IS NOT NULL
      THEN ABS(zone_t - prev_zone_t) / dt_s * 3600.0 ELSE NULL END AS zone_t_rate,
    CASE WHEN dt_s IS NOT NULL AND chw_supply_t IS NOT NULL AND prev_chw_supply_t IS NOT NULL
      THEN ABS(chw_supply_t - prev_chw_supply_t) / dt_s * 3600.0 ELSE NULL END AS chw_supply_t_rate,
    CASE WHEN dt_s IS NOT NULL AND chw_return_t IS NOT NULL AND prev_chw_return_t IS NOT NULL
      THEN ABS(chw_return_t - prev_chw_return_t) / dt_s * 3600.0 ELSE NULL END AS chw_return_t_rate,
    CASE WHEN dt_s IS NOT NULL AND hw_supply_t IS NOT NULL AND prev_hw_supply_t IS NOT NULL
      THEN ABS(hw_supply_t - prev_hw_supply_t) / dt_s * 3600.0 ELSE NULL END AS hw_supply_t_rate,
    CASE WHEN dt_s IS NOT NULL AND hw_return_t IS NOT NULL AND prev_hw_return_t IS NOT NULL
      THEN ABS(hw_return_t - prev_hw_return_t) / dt_s * 3600.0 ELSE NULL END AS hw_return_t_rate,
    CASE WHEN dt_s IS NOT NULL AND oa_h IS NOT NULL AND prev_oa_h IS NOT NULL
      THEN ABS(oa_h - prev_oa_h) / dt_s * 3600.0 ELSE NULL END AS oa_h_rate,
    CASE WHEN dt_s IS NOT NULL AND duct_static IS NOT NULL AND prev_duct_static IS NOT NULL
      THEN ABS(duct_static - prev_duct_static) / dt_s * 3600.0 ELSE NULL END AS duct_static_rate,
    CASE WHEN dt_s IS NOT NULL AND zone_t IS NOT NULL AND prev_zone_t IS NOT NULL
      THEN ABS(zone_t - prev_zone_t) ELSE NULL END AS zone_t_jump
  FROM s
),
base AS (
  SELECT
    equipment_id,
    timestamp_utc,
    CAST(CASE
      WHEN zone_t_jump IS NOT NULL
        AND dt_s IS NOT NULL
        AND dt_s > 0
        AND dt_s <= ({{ZONE_EXTREME_MINUTES}} * 60.0)
        AND zone_t_jump > {{ZONE_EXTREME_JUMP}} * {{SLEW_SCALE}}
      THEN 1
      WHEN in_transient = TRUE AND (
        (oa_t_rate IS NOT NULL AND oa_t_rate > {{OA_T_TRANSIENT_FAULT}} * {{SLEW_SCALE}})
        OR (rat_rate IS NOT NULL AND rat_rate > {{RAT_TRANSIENT_FAULT}} * {{SLEW_SCALE}})
        OR (mat_rate IS NOT NULL AND mat_rate > {{MAT_TRANSIENT_FAULT}} * {{SLEW_SCALE}})
        OR (sat_rate IS NOT NULL AND sat_rate > {{SAT_TRANSIENT_FAULT}} * {{SLEW_SCALE}})
        OR (zone_t_rate IS NOT NULL AND zone_t_rate > {{ZONE_T_TRANSIENT_FAULT}} * {{SLEW_SCALE}})
        OR (chw_supply_t_rate IS NOT NULL AND chw_supply_t_rate > {{CHW_SUPPLY_TRANSIENT_FAULT}} * {{SLEW_SCALE}})
        OR (chw_return_t_rate IS NOT NULL AND chw_return_t_rate > {{CHW_RETURN_TRANSIENT_FAULT}} * {{SLEW_SCALE}})
        OR (hw_supply_t_rate IS NOT NULL AND hw_supply_t_rate > {{HW_SUPPLY_TRANSIENT_FAULT}} * {{SLEW_SCALE}})
        OR (hw_return_t_rate IS NOT NULL AND hw_return_t_rate > {{HW_RETURN_TRANSIENT_FAULT}} * {{SLEW_SCALE}})
        OR (oa_h_rate IS NOT NULL AND oa_h_rate > {{OA_H_TRANSIENT_FAULT}} * {{SLEW_SCALE}})
        OR (duct_static_rate IS NOT NULL AND duct_static_rate > {{DUCT_STATIC_TRANSIENT_FAULT}} * {{SLEW_SCALE}})
      ) THEN 1
      WHEN in_transient = FALSE AND (
        (oa_t_rate IS NOT NULL AND oa_t_rate > {{OA_T_STEADY_FAULT}} * {{SLEW_SCALE}})
        OR (rat_rate IS NOT NULL AND rat_rate > {{RAT_STEADY_FAULT}} * {{SLEW_SCALE}})
        OR (mat_rate IS NOT NULL AND mat_rate > {{MAT_STEADY_FAULT}} * {{SLEW_SCALE}})
        OR (sat_rate IS NOT NULL AND sat_rate > {{SAT_STEADY_FAULT}} * {{SLEW_SCALE}})
        OR (zone_t_rate IS NOT NULL AND zone_t_rate > {{ZONE_T_STEADY_FAULT}} * {{SLEW_SCALE}})
        OR (chw_supply_t_rate IS NOT NULL AND chw_supply_t_rate > {{CHW_SUPPLY_STEADY_FAULT}} * {{SLEW_SCALE}})
        OR (chw_return_t_rate IS NOT NULL AND chw_return_t_rate > {{CHW_RETURN_STEADY_FAULT}} * {{SLEW_SCALE}})
        OR (hw_supply_t_rate IS NOT NULL AND hw_supply_t_rate > {{HW_SUPPLY_STEADY_FAULT}} * {{SLEW_SCALE}})
        OR (hw_return_t_rate IS NOT NULL AND hw_return_t_rate > {{HW_RETURN_STEADY_FAULT}} * {{SLEW_SCALE}})
        OR (oa_h_rate IS NOT NULL AND oa_h_rate > {{OA_H_STEADY_FAULT}} * {{SLEW_SCALE}})
        OR (duct_static_rate IS NOT NULL AND duct_static_rate > {{DUCT_STATIC_STEADY_FAULT}} * {{SLEW_SCALE}})
      ) THEN 1
      ELSE 0
    END AS INT) AS raw_fault
  FROM rated
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
