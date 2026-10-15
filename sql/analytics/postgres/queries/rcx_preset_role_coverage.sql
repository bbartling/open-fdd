-- Soft-OPEN analytics pack: role coverage inventory for RCx preset eligibility Soft-OPEN.
-- Parameter: $1 = site_id. Preset catalog stays in Rust; this feeds coverage only.
SELECT
  split_part(openfdd_key, '.', 1) AS equipment_id,
  split_part(openfdd_key, '.', 2) AS role,
  count(*)::bigint AS n,
  min(ts) AS first_ts,
  max(ts) AS last_ts
FROM sample
WHERE site_id = $1
  AND val IS NOT NULL
  AND split_part(openfdd_key, '.', 2) IN (
    'oa_t', 'web_oa_t', 'sat', 'mat', 'rat', 'oa_damper_pct',
    'zone_t', 'dsp', 'chw_supply_t', 'hw_supply_t',
    'fan_cmd', 'clg_valve_pct', 'htg_valve_pct'
  )
GROUP BY 1, 2
ORDER BY 1, 2
LIMIT 5000;
