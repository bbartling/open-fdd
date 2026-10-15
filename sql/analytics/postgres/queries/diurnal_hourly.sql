-- Soft-OPEN analytics pack: hourly mean by role (diurnal shape Soft-OPEN).
-- Parameter: $1 = site_id. Soft-OPEN ≠ FQ.
SELECT
  split_part(openfdd_key, '.', 1) AS equipment_id,
  split_part(openfdd_key, '.', 2) AS role,
  extract(hour FROM ts AT TIME ZONE 'UTC')::int AS hour_utc,
  avg(val) AS avg_val,
  count(*)::bigint AS n
FROM sample
WHERE site_id = $1
  AND val IS NOT NULL
  AND split_part(openfdd_key, '.', 2) IN (
    'oa_t', 'web_oa_t', 'sat', 'mat', 'rat', 'zone_t',
    'fan_cmd', 'clg_valve_pct', 'htg_valve_pct'
  )
GROUP BY 1, 2, 3
ORDER BY 1, 2, 3
LIMIT 5000;
