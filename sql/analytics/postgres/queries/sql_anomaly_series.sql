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
    split_part(openfdd_key, '.', 1) AS equipment_id,
    split_part(openfdd_key, '.', 2) AS role,
    val
  FROM sample
  WHERE site_id = $1
    AND ($2::timestamptz IS NULL OR ts >= $2)
    AND ($3::timestamptz IS NULL OR ts < $3)
    AND (
      $4::text[] IS NULL
      OR cardinality($4) = 0
      OR split_part(openfdd_key, '.', 1) = ANY ($4)
    )
    AND split_part(openfdd_key, '.', 2) IN (
      'sat', 'mat', 'rat', 'oa_t', 'web_oa_t', 'zone_t', 'dsp'
    )
)
SELECT
  equipment_id,
  role,
  count(val)::bigint AS n,
  count(*) FILTER (WHERE val IS NULL)::bigint AS n_null,
  stddev_samp(val) AS stddev_val
FROM keyed
GROUP BY equipment_id, role
ORDER BY equipment_id, role;
