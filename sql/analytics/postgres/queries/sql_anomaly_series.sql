-- Per-series coverage for the anomaly event table. This does not score
-- z. Short, constant, and missing series stay visible when they produce
-- no event rows.
--
-- Parameters:
--   $1 site_id
--   $2 window start (timestamptz, NULL = open)
--   $3 window end   (timestamptz, NULL = open, half-open)
--   $4 equipment_ids (text[], NULL/empty = all). Exact id match.
-- Role list matches sql_anomaly_zscore.sql.
WITH keyed AS (
  SELECT
    a.equipment_id,
    a.role,
    a.openfdd_key,
    s.val
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
    AND a.role IN (
      'sat', 'mat', 'rat', 'oa_t', 'web_oa_t', 'zone_t', 'dsp'
    )
)
SELECT
  equipment_id,
  role,
  openfdd_key,
  count(val)::bigint AS n,
  count(*) FILTER (WHERE val IS NULL)::bigint AS n_null,
  stddev_samp(val) AS stddev_val
FROM keyed
GROUP BY equipment_id, role, openfdd_key
ORDER BY equipment_id, role, openfdd_key;
