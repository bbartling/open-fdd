-- Per-equipment economizer deltas.
-- Parameters:
--   $1 = site_id
--   $2 = window start (timestamptz, NULL = open)
--   $3 = window end   (timestamptz, NULL = open)
--   $4 = equipment_ids (text[], NULL/empty = all)
--   $5 = minimum |OAT−RAT| (°F). Rows below this are not qualified.
-- x = OAT − RAT (delta_or_f), y = MAT − RAT (delta_mr_f).
-- A row is qualified only with explicit fan_status proof, a measured MAT,
-- and |OAT−RAT| at or above $5. Missing fan status is not fan-on.
-- MAT residual is the measured MAT minus the damper mixing model, and is
-- null when the damper feedback is absent.
WITH keyed AS (
  SELECT
    ts,
    split_part(openfdd_key, '.', 1) AS equipment_id,
    max(val) FILTER (WHERE split_part(openfdd_key, '.', 2) = 'oa_t') AS oa_t,
    max(val) FILTER (WHERE split_part(openfdd_key, '.', 2) = 'rat') AS rat,
    max(val) FILTER (WHERE split_part(openfdd_key, '.', 2) = 'mat') AS mat,
    max(val) FILTER (WHERE split_part(openfdd_key, '.', 2) = 'sat') AS sat,
    max(val) FILTER (WHERE split_part(openfdd_key, '.', 2) = 'oa_damper_pct') AS oa_damper_pct,
    max(val) FILTER (WHERE split_part(openfdd_key, '.', 2) = 'fan_status') AS fan_status
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
      'oa_t', 'rat', 'mat', 'sat', 'oa_damper_pct', 'fan_status'
    )
  GROUP BY ts, split_part(openfdd_key, '.', 1)
)
SELECT
  ts,
  equipment_id,
  oa_t,
  rat,
  mat,
  sat,
  oa_damper_pct,
  (oa_t - rat) AS delta_or_f,
  (mat - rat) AS delta_mr_f,
  CASE
    WHEN oa_damper_pct IS NULL THEN NULL
    ELSE mat - (rat + (oa_damper_pct / 100.0) * (oa_t - rat))
  END AS mat_resid_f,
  TRUE AS fan_on,
  TRUE AS identifiable
FROM keyed
WHERE oa_t IS NOT NULL
  AND rat IS NOT NULL
  AND mat IS NOT NULL
  AND fan_status IS NOT NULL
  AND fan_status > 0.05
  AND abs(oa_t - rat) >= $5::double precision
ORDER BY ts DESC
LIMIT 2000;
