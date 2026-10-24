-- BAS vs web outdoor-air temperature pairs.
-- Equipment and role come from the current binding.
-- A role with two keys is omitted rather than maxed.
-- Parameters:
--   $1 = site_id
--   $2 = window start (timestamptz, NULL = open)
--   $3 = window end   (timestamptz, NULL = open)
--   $4 = equipment_ids (text[], NULL/empty = all)
WITH unique_role AS (
  SELECT site_id, equipment_id, role, min(openfdd_key) AS openfdd_key
  FROM authorized_series
  GROUP BY site_id, equipment_id, role
  HAVING count(*) = 1
),
bas AS (
  SELECT s.ts, s.val AS bas_oa_t, u.equipment_id
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
    AND u.role = 'oa_t'
),
web AS (
  SELECT s.ts, s.val AS web_oa_t
  FROM sample s
  JOIN unique_role u
    ON u.site_id = s.site_id
   AND u.openfdd_key = s.openfdd_key
  WHERE s.site_id = $1
    AND ($2::timestamptz IS NULL OR s.ts >= $2)
    AND ($3::timestamptz IS NULL OR s.ts < $3)
    AND u.role = 'web_oa_t'
    AND (
      SELECT count(*)
      FROM unique_role c
      WHERE c.site_id = $1 AND c.role = 'web_oa_t'
    ) = 1
)
SELECT b.ts, b.equipment_id, b.bas_oa_t, w.web_oa_t, (b.bas_oa_t - w.web_oa_t) AS delta_f
FROM bas b
JOIN web w ON w.ts = b.ts
ORDER BY b.ts DESC, b.equipment_id
LIMIT 2000;
