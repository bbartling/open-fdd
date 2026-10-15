-- Soft-OPEN analytics pack: per-equipment economizer deltas (not cross-equip group).
-- Parameters:
--   $1 = site_id
--   $2 = window start (timestamptz, NULL = open)
--   $3 = window end   (timestamptz, NULL = open)
--   $4 = equipment_ids (text[], NULL/empty = all)
-- x = OAT − RAT (delta_or_f), y = MAT − RAT (delta_mr_f).
WITH keyed AS (
  SELECT
    ts,
    split_part(openfdd_key, '.', 1) AS equipment_id,
    max(val) FILTER (WHERE openfdd_key LIKE '%.oa_t') AS oa_t,
    max(val) FILTER (WHERE openfdd_key LIKE '%.rat') AS rat,
    max(val) FILTER (WHERE openfdd_key LIKE '%.mat') AS mat,
    max(val) FILTER (WHERE openfdd_key LIKE '%.sat') AS sat,
    max(val) FILTER (WHERE openfdd_key LIKE '%.oa_damper_pct') AS oa_damper_pct
  FROM sample
  WHERE site_id = $1
    AND ($2::timestamptz IS NULL OR ts >= $2)
    AND ($3::timestamptz IS NULL OR ts < $3)
    AND (
      $4::text[] IS NULL
      OR cardinality($4) = 0
      OR split_part(openfdd_key, '.', 1) = ANY ($4)
    )
    AND (
      openfdd_key LIKE '%.oa_t' OR openfdd_key LIKE '%.rat'
      OR openfdd_key LIKE '%.mat' OR openfdd_key LIKE '%.sat'
      OR openfdd_key LIKE '%.oa_damper_pct'
    )
  GROUP BY ts, split_part(openfdd_key, '.', 1)
)
SELECT ts, equipment_id, oa_t, rat, mat, sat, oa_damper_pct,
       (oa_t - rat) AS delta_or_f,
       (mat - rat) AS delta_mr_f
FROM keyed
WHERE oa_t IS NOT NULL AND rat IS NOT NULL AND mat IS NOT NULL
ORDER BY ts DESC
LIMIT 2000;
