-- Role coverage for RCx preset eligibility. One row per bound key.
-- Parameters:
--   $1 = site_id
--   $2 = window start (timestamptz, NULL = open)
--   $3 = window end   (timestamptz, NULL = open)
--   $4 = equipment_ids (text[], NULL/empty = all)
SELECT
  a.equipment_id,
  a.role,
  a.openfdd_key,
  count(*)::bigint AS n,
  min(s.ts) AS first_ts,
  max(s.ts) AS last_ts
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
  AND a.role IN (
    'oa_t', 'web_oa_t', 'sat', 'mat', 'rat', 'oa_damper_pct',
    'zone_t', 'dsp', 'chw_supply_t', 'hw_supply_t',
    'fan_cmd', 'clg_valve_pct', 'htg_valve_pct'
  )
GROUP BY a.equipment_id, a.role, a.openfdd_key
ORDER BY a.equipment_id, a.role, a.openfdd_key
LIMIT 5000;
