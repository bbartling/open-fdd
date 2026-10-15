-- Soft-OPEN analytics pack: simple z-score anomaly flags on common sensor roles.
-- Parameters:
--   $1 = site_id
--   $2 = window start (timestamptz, NULL = open)
--   $3 = window end   (timestamptz, NULL = open)
--   $4 = equipment_ids (text[], NULL/empty = all)
-- Soft-OPEN ≠ FQ (not full SV/oracle suite).
WITH role_stats AS (
  SELECT
    split_part(openfdd_key, '.', 1) AS equipment_id,
    split_part(openfdd_key, '.', 2) AS role,
    avg(val) AS avg_val,
    stddev_samp(val) AS stddev_val,
    count(*)::bigint AS n
  FROM sample
  WHERE site_id = $1
    AND ($2::timestamptz IS NULL OR ts >= $2)
    AND ($3::timestamptz IS NULL OR ts < $3)
    AND (
      $4::text[] IS NULL
      OR cardinality($4) = 0
      OR split_part(openfdd_key, '.', 1) = ANY ($4)
    )
    AND val IS NOT NULL
    AND split_part(openfdd_key, '.', 2) IN (
      'sat', 'mat', 'rat', 'oa_t', 'web_oa_t', 'zone_t', 'dsp'
    )
  GROUP BY 1, 2
  HAVING count(*) >= 24 AND stddev_samp(val) IS NOT NULL AND stddev_samp(val) > 0
),
scored AS (
  SELECT
    split_part(s.openfdd_key, '.', 1) AS equipment_id,
    split_part(s.openfdd_key, '.', 2) AS role,
    s.ts,
    s.val,
    r.avg_val,
    r.stddev_val,
    abs((s.val - r.avg_val) / r.stddev_val) AS z_abs
  FROM sample s
  JOIN role_stats r
    ON r.equipment_id = split_part(s.openfdd_key, '.', 1)
   AND r.role = split_part(s.openfdd_key, '.', 2)
  WHERE s.site_id = $1
    AND ($2::timestamptz IS NULL OR s.ts >= $2)
    AND ($3::timestamptz IS NULL OR s.ts < $3)
    AND (
      $4::text[] IS NULL
      OR cardinality($4) = 0
      OR split_part(s.openfdd_key, '.', 1) = ANY ($4)
    )
    AND s.val IS NOT NULL
)
SELECT
  equipment_id,
  role,
  ts,
  val,
  avg_val,
  stddev_val,
  z_abs,
  CASE WHEN z_abs >= 3.0 THEN 'ANOMALY' ELSE 'OK' END AS anomaly_flag
FROM scored
WHERE z_abs >= 3.0
ORDER BY z_abs DESC, ts DESC
LIMIT 2000;
