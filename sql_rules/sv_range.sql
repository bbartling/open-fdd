-- sv_range.sql — SV-RANGE sensor hard-range sweep + confirm
WITH h AS (
  SELECT * FROM history
),
base AS (
  SELECT
    equipment_id,
    timestamp_utc,
    CAST(CASE
      WHEN
        (oa_t IS NOT NULL AND (oa_t < -60.0 OR oa_t > 130.0))
        OR (rat IS NOT NULL AND (rat < 40.0 OR rat > 100.0))
        OR (mat IS NOT NULL AND (mat < -20.0 OR mat > 110.0))
        OR (sat IS NOT NULL AND (sat < 30.0 OR sat > 150.0))
        OR (zone_t IS NOT NULL AND (zone_t < 40.0 OR zone_t > 100.0))
        OR (chw_supply_t IS NOT NULL AND (chw_supply_t < 30.0 OR chw_supply_t > 80.0))
        OR (chw_return_t IS NOT NULL AND (chw_return_t < 30.0 OR chw_return_t > 90.0))
        OR (hw_supply_t IS NOT NULL AND (hw_supply_t < 40.0 OR hw_supply_t > 220.0))
        OR (hw_return_t IS NOT NULL AND (hw_return_t < 40.0 OR hw_return_t > 220.0))
        OR (oa_h IS NOT NULL AND (oa_h < 0.0 OR oa_h > 100.0))
        OR (duct_static IS NOT NULL AND (duct_static < -1.0 OR duct_static > 8.0))
      THEN 1 ELSE 0 END AS INT) AS raw_fault
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
