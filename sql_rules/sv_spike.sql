-- sv_spike.sql — SV-SPIKE sample-to-sample spike sweep + confirm
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
    ABS(oa_t - LAG(oa_t) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc)) AS oa_t_jump,
    ABS(rat - LAG(rat) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc)) AS rat_jump,
    ABS(mat - LAG(mat) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc)) AS mat_jump,
    ABS(sat - LAG(sat) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc)) AS sat_jump,
    ABS(zone_t - LAG(zone_t) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc)) AS zone_t_jump,
    ABS(chw_supply_t - LAG(chw_supply_t) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc)) AS chw_supply_t_jump,
    ABS(chw_return_t - LAG(chw_return_t) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc)) AS chw_return_t_jump,
    ABS(hw_supply_t - LAG(hw_supply_t) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc)) AS hw_supply_t_jump,
    ABS(hw_return_t - LAG(hw_return_t) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc)) AS hw_return_t_jump,
    ABS(oa_h - LAG(oa_h) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc)) AS oa_h_jump,
    ABS(duct_static - LAG(duct_static) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc)) AS duct_static_jump
  FROM h
),
base AS (
  SELECT
    equipment_id,
    timestamp_utc,
    CAST(CASE
      WHEN
        (oa_t IS NOT NULL AND oa_t_jump > 36.0 * {{SPIKE_SCALE}})
        OR (rat IS NOT NULL AND rat_jump > 12.0 * {{SPIKE_SCALE}})
        OR (mat IS NOT NULL AND mat_jump > 25.0 * {{SPIKE_SCALE}})
        OR (sat IS NOT NULL AND sat_jump > 40.0 * {{SPIKE_SCALE}})
        OR (zone_t IS NOT NULL AND zone_t_jump > 12.0 * {{SPIKE_SCALE}})
        OR (chw_supply_t IS NOT NULL AND chw_supply_t_jump > 20.0 * {{SPIKE_SCALE}})
        OR (chw_return_t IS NOT NULL AND chw_return_t_jump > 20.0 * {{SPIKE_SCALE}})
        OR (hw_supply_t IS NOT NULL AND hw_supply_t_jump > 60.0 * {{SPIKE_SCALE}})
        OR (hw_return_t IS NOT NULL AND hw_return_t_jump > 60.0 * {{SPIKE_SCALE}})
        OR (oa_h IS NOT NULL AND oa_h_jump > 25.0 * {{SPIKE_SCALE}})
        OR (duct_static IS NOT NULL AND duct_static_jump > 2.0 * {{SPIKE_SCALE}})
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
