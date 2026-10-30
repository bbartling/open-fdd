-- Hunting proxy. One row per bound key, not a mix of two sensors.
-- Preserve the legacy 8-unit spread by semantic role after metric-c-v2 storage:
-- temperature (degF delta -> delta_degC), duct air pressure (in.w.c. -> Pa),
-- and unitless percent/cmd roles (identity). These are role IDs, never site IDs.
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
  avg(s.val) AS avg_val,
  stddev_samp(s.val) AS stddev_val,
  CASE
    WHEN count(*) >= 24 AND stddev_samp(s.val) IS NOT NULL AND (
      (a.role IN ('sat', 'zone_t') AND stddev_samp(s.val) > 4.444444444444445)
      OR (a.role = 'dsp' AND stddev_samp(s.val) > 1990.72)
      OR (a.role NOT IN ('sat', 'zone_t', 'dsp') AND stddev_samp(s.val) > 8.0)
    )
      THEN 'HUNT_PROXY'
    ELSE 'OK'
  END AS hunt_flag
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
    'clg_valve_pct', 'htg_valve_pct', 'oa_damper_pct', 'fan_cmd',
    'dsp', 'sat', 'zone_t'
  )
GROUP BY a.equipment_id, a.role, a.openfdd_key
HAVING count(*) >= 12
ORDER BY stddev_val DESC NULLS LAST, a.openfdd_key
LIMIT 2000;
