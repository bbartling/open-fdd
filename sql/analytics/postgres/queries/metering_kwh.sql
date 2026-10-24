-- Energy aggregates. One row per bound key.
-- Parameters:
--   $1 = site_id
--   $2 = window start (timestamptz, NULL = open)
--   $3 = window end   (timestamptz, NULL = open)
--   $4 = equipment_ids (text[], NULL/empty = all)
SELECT
  a.equipment_id,
  a.role,
  a.openfdd_key,
  date_trunc('day', s.ts) AS day_utc,
  count(*)::bigint AS n,
  min(s.val) AS min_val,
  max(s.val) AS max_val,
  avg(s.val) AS avg_val,
  (max(s.val) - min(s.val)) AS delta_val
FROM sample s
JOIN authorized_series a
  ON a.site_id = s.site_id
 AND a.openfdd_key = s.openfdd_key
WHERE s.site_id = $1
  AND ($2::timestamptz IS NULL OR s.ts >= $2)
  AND ($3::timestamptz IS NULL OR s.ts < $3)
  AND (
    $4::text[] IS NULL
    OR cardinality($4) = 0
    OR a.equipment_id = ANY ($4)
  )
  AND s.val IS NOT NULL
  AND (
    a.role LIKE '%kwh%'
    OR a.role LIKE '%_kwh'
    OR a.role IN (
      'electric_kwh', 'gas_therm', 'steam_mlb', 'water_gal', 'power_kw'
    )
  )
GROUP BY a.equipment_id, a.role, a.openfdd_key, 4
ORDER BY 4 DESC, a.equipment_id, a.role, a.openfdd_key
LIMIT 2000;
