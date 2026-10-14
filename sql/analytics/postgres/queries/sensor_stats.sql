-- Soft-OPEN analytics pack: per-equipment/role basic sensor statistics.
-- Parameter: $1 = site_id. Full hunting/staleness Soft-OPEN later.
SELECT
  split_part(openfdd_key, '.', 1) AS equipment_id,
  split_part(openfdd_key, '.', 2) AS role,
  count(*)::bigint AS n,
  min(val) AS min_val,
  max(val) AS max_val,
  avg(val) AS avg_val,
  stddev_samp(val) AS stddev_val,
  min(ts) AS first_ts,
  max(ts) AS last_ts
FROM sample
WHERE site_id = $1
  AND val IS NOT NULL
GROUP BY 1, 2
ORDER BY 1, 2
LIMIT 2000;
