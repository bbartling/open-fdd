-- Per-equipment economizer deltas.
-- Parameters:
--   $1 = site_id
--   $2 = window start (timestamptz, NULL = open)
--   $3 = window end   (timestamptz, NULL = open)
--   $4 = equipment_ids (text[], NULL/empty = all)
--   $5 = minimum |OAT−RAT| (Δ°C, scale-only). Rows below this are not qualified.
-- x = OAT − RAT (delta_or_f field, SI °C), y = MAT − RAT (delta_mr_f, SI °C).
-- A row is qualified only with explicit fan_status proof, a measured MAT,
-- and |OAT−RAT| at or above $5. Missing fan status is not fan-on.
-- MAT residual is the measured MAT minus the damper mixing model, and is
-- null when the damper feedback is absent.
-- A role with two bound keys is left null. It is not maxed into one input.
WITH unique_role AS (
  SELECT site_id, equipment_id, role, min(openfdd_key) AS openfdd_key
  FROM authorized_series
  GROUP BY site_id, equipment_id, role
  HAVING count(*) = 1
),
keyed AS (
  SELECT
    s.ts,
    u.equipment_id,
    max(s.val) FILTER (WHERE u.role = 'oa_t') AS oa_t,
    max(s.val) FILTER (WHERE u.role = 'rat') AS rat,
    max(s.val) FILTER (WHERE u.role = 'mat') AS mat,
    max(s.val) FILTER (WHERE u.role = 'sat') AS sat,
    max(s.val) FILTER (WHERE u.role = 'oa_damper_pct') AS oa_damper_pct,
    max(s.val) FILTER (WHERE u.role = 'fan_status') AS fan_status
  FROM sample s
  JOIN unique_role u
    ON u.site_id = s.site_id
   AND u.openfdd_key = s.openfdd_key
  WHERE s.site_id = $1
    AND ($2::timestamptz IS NULL OR s.ts >= $2)
    AND ($3::timestamptz IS NULL OR s.ts < $3)
    AND (
      $4::text[] IS NULL
      OR cardinality($4) = 0
      OR u.equipment_id = ANY ($4)
    )
    AND u.role IN (
      'oa_t', 'rat', 'mat', 'sat', 'oa_damper_pct', 'fan_status'
    )
  GROUP BY s.ts, u.equipment_id
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
