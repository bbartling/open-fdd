-- sv_stale.sql — SV-STALE all-modeled-sensors unchanged + confirm
-- Match Vibe19 `_sweep_stale`: only columns that ever have data for the
-- equipment participate; null rows are not "unchanged"; require a full window
-- (`min_periods=window`). Projected all-null optional roles must not force FAULT.
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
    MAX(CASE WHEN oa_t IS NOT NULL THEN 1 ELSE 0 END)
      OVER (PARTITION BY equipment_id) AS oa_t_present,
    MAX(CASE WHEN rat IS NOT NULL THEN 1 ELSE 0 END)
      OVER (PARTITION BY equipment_id) AS rat_present,
    MAX(CASE WHEN mat IS NOT NULL THEN 1 ELSE 0 END)
      OVER (PARTITION BY equipment_id) AS mat_present,
    MAX(CASE WHEN sat IS NOT NULL THEN 1 ELSE 0 END)
      OVER (PARTITION BY equipment_id) AS sat_present,
    MAX(CASE WHEN zone_t IS NOT NULL THEN 1 ELSE 0 END)
      OVER (PARTITION BY equipment_id) AS zone_t_present,
    MAX(CASE WHEN chw_supply_t IS NOT NULL THEN 1 ELSE 0 END)
      OVER (PARTITION BY equipment_id) AS chw_supply_t_present,
    MAX(CASE WHEN chw_return_t IS NOT NULL THEN 1 ELSE 0 END)
      OVER (PARTITION BY equipment_id) AS chw_return_t_present,
    MAX(CASE WHEN hw_supply_t IS NOT NULL THEN 1 ELSE 0 END)
      OVER (PARTITION BY equipment_id) AS hw_supply_t_present,
    MAX(CASE WHEN hw_return_t IS NOT NULL THEN 1 ELSE 0 END)
      OVER (PARTITION BY equipment_id) AS hw_return_t_present,
    MAX(CASE WHEN oa_h IS NOT NULL THEN 1 ELSE 0 END)
      OVER (PARTITION BY equipment_id) AS oa_h_present,
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
      WHEN window_samples >= {{WINDOW_ROWS}}
       AND (
         oa_t_present + rat_present + mat_present + sat_present + zone_t_present
         + chw_supply_t_present + chw_return_t_present + hw_supply_t_present
         + hw_return_t_present + oa_h_present
       ) > 0
       AND (oa_t_present = 0 OR (oa_t IS NOT NULL AND (oa_t_max - oa_t_min) <= 0.000001))
       AND (rat_present = 0 OR (rat IS NOT NULL AND (rat_max - rat_min) <= 0.000001))
       AND (mat_present = 0 OR (mat IS NOT NULL AND (mat_max - mat_min) <= 0.000001))
       AND (sat_present = 0 OR (sat IS NOT NULL AND (sat_max - sat_min) <= 0.000001))
       AND (zone_t_present = 0 OR (zone_t IS NOT NULL AND (zone_t_max - zone_t_min) <= 0.000001))
       AND (chw_supply_t_present = 0 OR (chw_supply_t IS NOT NULL AND (chw_supply_t_max - chw_supply_t_min) <= 0.000001))
       AND (chw_return_t_present = 0 OR (chw_return_t IS NOT NULL AND (chw_return_t_max - chw_return_t_min) <= 0.000001))
       AND (hw_supply_t_present = 0 OR (hw_supply_t IS NOT NULL AND (hw_supply_t_max - hw_supply_t_min) <= 0.000001))
       AND (hw_return_t_present = 0 OR (hw_return_t IS NOT NULL AND (hw_return_t_max - hw_return_t_min) <= 0.000001))
       AND (oa_h_present = 0 OR (oa_h IS NOT NULL AND (oa_h_max - oa_h_min) <= 0.000001))
      THEN 1 ELSE 0 END AS INT) AS raw_fault
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
