-- sv_flatline.sql — SV-FLATLINE stuck-sensor sweep + confirm
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
    MAX(oa_t) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS BETWEEN {{WINDOW_ROWS_MINUS_ONE}} PRECEDING AND CURRENT ROW) AS oa_t_max,
    MIN(oa_t) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS BETWEEN {{WINDOW_ROWS_MINUS_ONE}} PRECEDING AND CURRENT ROW) AS oa_t_min,
    MAX(rat) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS BETWEEN {{WINDOW_ROWS_MINUS_ONE}} PRECEDING AND CURRENT ROW) AS rat_max,
    MIN(rat) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS BETWEEN {{WINDOW_ROWS_MINUS_ONE}} PRECEDING AND CURRENT ROW) AS rat_min,
    MAX(mat) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS BETWEEN {{WINDOW_ROWS_MINUS_ONE}} PRECEDING AND CURRENT ROW) AS mat_max,
    MIN(mat) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS BETWEEN {{WINDOW_ROWS_MINUS_ONE}} PRECEDING AND CURRENT ROW) AS mat_min,
    MAX(sat) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS BETWEEN {{WINDOW_ROWS_MINUS_ONE}} PRECEDING AND CURRENT ROW) AS sat_max,
    MIN(sat) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS BETWEEN {{WINDOW_ROWS_MINUS_ONE}} PRECEDING AND CURRENT ROW) AS sat_min,
    MAX(zone_t) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS BETWEEN {{WINDOW_ROWS_MINUS_ONE}} PRECEDING AND CURRENT ROW) AS zone_t_max,
    MIN(zone_t) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS BETWEEN {{WINDOW_ROWS_MINUS_ONE}} PRECEDING AND CURRENT ROW) AS zone_t_min,
    MAX(chw_supply_t) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS BETWEEN {{WINDOW_ROWS_MINUS_ONE}} PRECEDING AND CURRENT ROW) AS chw_supply_t_max,
    MIN(chw_supply_t) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS BETWEEN {{WINDOW_ROWS_MINUS_ONE}} PRECEDING AND CURRENT ROW) AS chw_supply_t_min,
    MAX(chw_return_t) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS BETWEEN {{WINDOW_ROWS_MINUS_ONE}} PRECEDING AND CURRENT ROW) AS chw_return_t_max,
    MIN(chw_return_t) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS BETWEEN {{WINDOW_ROWS_MINUS_ONE}} PRECEDING AND CURRENT ROW) AS chw_return_t_min,
    MAX(hw_supply_t) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS BETWEEN {{WINDOW_ROWS_MINUS_ONE}} PRECEDING AND CURRENT ROW) AS hw_supply_t_max,
    MIN(hw_supply_t) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS BETWEEN {{WINDOW_ROWS_MINUS_ONE}} PRECEDING AND CURRENT ROW) AS hw_supply_t_min,
    MAX(hw_return_t) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS BETWEEN {{WINDOW_ROWS_MINUS_ONE}} PRECEDING AND CURRENT ROW) AS hw_return_t_max,
    MIN(hw_return_t) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS BETWEEN {{WINDOW_ROWS_MINUS_ONE}} PRECEDING AND CURRENT ROW) AS hw_return_t_min,
    MAX(oa_h) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS BETWEEN {{WINDOW_ROWS_MINUS_ONE}} PRECEDING AND CURRENT ROW) AS oa_h_max,
    MIN(oa_h) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS BETWEEN {{WINDOW_ROWS_MINUS_ONE}} PRECEDING AND CURRENT ROW) AS oa_h_min,
    COUNT(*) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS BETWEEN {{WINDOW_ROWS_MINUS_ONE}} PRECEDING AND CURRENT ROW) AS window_samples
  FROM h
),
base AS (
  SELECT
    equipment_id,
    timestamp_utc,
    CAST(CASE
      WHEN window_samples >= {{MINIMUM_SAMPLES}} AND (
        (oa_t IS NOT NULL AND (oa_t_max - oa_t_min) <= {{FLATLINE_TOL}})
        OR (rat IS NOT NULL AND (rat_max - rat_min) <= {{FLATLINE_TOL}})
        OR (mat IS NOT NULL AND (mat_max - mat_min) <= {{FLATLINE_TOL}})
        OR (sat IS NOT NULL AND (sat_max - sat_min) <= {{FLATLINE_TOL}})
        OR (zone_t IS NOT NULL AND (zone_t_max - zone_t_min) <= {{FLATLINE_TOL}})
        OR (chw_supply_t IS NOT NULL AND (chw_supply_t_max - chw_supply_t_min) <= {{FLATLINE_TOL}})
        OR (chw_return_t IS NOT NULL AND (chw_return_t_max - chw_return_t_min) <= {{FLATLINE_TOL}})
        OR (hw_supply_t IS NOT NULL AND (hw_supply_t_max - hw_supply_t_min) <= {{FLATLINE_TOL}})
        OR (hw_return_t IS NOT NULL AND (hw_return_t_max - hw_return_t_min) <= {{FLATLINE_TOL}})
        OR (oa_h IS NOT NULL AND (oa_h_max - oa_h_min) <= {{FLATLINE_TOL}})
      ) THEN 1 ELSE 0 END AS INT) AS raw_fault
  FROM w
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
