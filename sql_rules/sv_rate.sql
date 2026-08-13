-- sv_rate.sql — Context-aware sensor rate of change (portable channels)
-- Still a screening placeholder vs full pandas rate profiles; wires mat/zone/rat/sat
-- so cases without oa_t are not silently PASS-0.
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
base AS (
  SELECT
    equipment_id,
    timestamp_utc,
    CAST(CASE
      WHEN prev_ts IS NULL THEN 0
      WHEN CAST(EXTRACT(EPOCH FROM (timestamp_utc - prev_ts)) AS DOUBLE) > {{PERSISTENCE_MIN}} * 60.0 THEN 0
      WHEN oa_t IS NOT NULL AND prev_oa_t IS NOT NULL AND ABS(oa_t - prev_oa_t) > 5.0 THEN 1
      WHEN mat IS NOT NULL AND prev_mat IS NOT NULL AND ABS(mat - prev_mat) > 5.0 THEN 1
      WHEN zone_t IS NOT NULL AND prev_zone_t IS NOT NULL AND ABS(zone_t - prev_zone_t) > 5.0 THEN 1
      WHEN rat IS NOT NULL AND prev_rat IS NOT NULL AND ABS(rat - prev_rat) > 5.0 THEN 1
      WHEN sat IS NOT NULL AND prev_sat IS NOT NULL AND ABS(sat - prev_sat) > 5.0 THEN 1
      ELSE 0
    END AS INT) AS raw_fault
  FROM h
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
