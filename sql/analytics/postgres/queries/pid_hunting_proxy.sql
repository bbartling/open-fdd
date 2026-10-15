-- Soft-OPEN analytics pack: hunting proxy via role stddev (not full PID-HUNT suite).
-- Parameter: $1 = site_id. Soft-OPEN ≠ FQ.
SELECT
  split_part(openfdd_key, '.', 1) AS equipment_id,
  split_part(openfdd_key, '.', 2) AS role,
  count(*)::bigint AS n,
  avg(val) AS avg_val,
  stddev_samp(val) AS stddev_val,
  CASE
    WHEN count(*) >= 24 AND stddev_samp(val) IS NOT NULL AND stddev_samp(val) > 8.0
      THEN 'HUNT_PROXY'
    ELSE 'OK'
  END AS hunt_flag
FROM sample
WHERE site_id = $1
  AND val IS NOT NULL
  AND split_part(openfdd_key, '.', 2) IN (
    'clg_valve_pct', 'htg_valve_pct', 'oa_damper_pct', 'fan_cmd',
    'dsp', 'sat', 'zone_t'
  )
GROUP BY 1, 2
HAVING count(*) >= 12
ORDER BY stddev_val DESC NULLS LAST
LIMIT 2000;
