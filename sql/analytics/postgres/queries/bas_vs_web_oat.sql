-- BAS vs web outdoor-air temperature pairs (same join policy as OAT-METEO).
-- Local oa_t uses the site binding chosen in Rust (primary_reference, else
-- default_lowest_binding). Web OAT is joined as-of each BAS timestamp; samples
-- whose last web value is older than $6 seconds are omitted (not assessed).
-- Parameters:
--   $1 = site_id
--   $2 = window start (timestamptz, NULL = open)
--   $3 = window end   (timestamptz, NULL = open)
--   $4 = equipment_ids (text[], NULL/empty = all)
--   $5 = selected site oa_t openfdd_key (from resolve_site_oa_t_reference)
--   $6 = web as-of bound seconds (web cadence + margin, same as OAT-METEO)
--   $7 = row limit (caller-validated max_points)
WITH web_unique AS (
  SELECT count(*) AS n
  FROM authorized_series c
  WHERE c.site_id = $1 AND c.role = 'web_oa_t'
),
web_points AS (
  SELECT s.ts, s.val AS web_oa_t
  FROM sample s
  JOIN authorized_series u
    ON u.site_id = s.site_id
   AND u.openfdd_key = s.openfdd_key
  CROSS JOIN web_unique wu
  WHERE s.site_id = $1
    AND (
      $2::timestamptz IS NULL
      OR s.ts >= $2 - make_interval(secs => ($6::double precision))
    )
    AND ($3::timestamptz IS NULL OR s.ts < $3)
    AND u.role = 'web_oa_t'
    AND wu.n = 1
),
bas AS (
  SELECT s.ts, s.val AS bas_oa_t, u.equipment_id
  FROM sample s
  JOIN authorized_series u
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
    AND u.openfdd_key = $5
),
joined AS (
  SELECT
    b.ts,
    b.equipment_id,
    b.bas_oa_t,
    (
      SELECT wp.web_oa_t
      FROM web_points wp
      WHERE wp.ts <= b.ts
      ORDER BY wp.ts DESC
      LIMIT 1
    ) AS web_oa_t,
    (
      SELECT wp.ts
      FROM web_points wp
      WHERE wp.ts <= b.ts
      ORDER BY wp.ts DESC
      LIMIT 1
    ) AS web_ts
  FROM bas b
)
SELECT
  j.ts,
  j.equipment_id,
  j.bas_oa_t,
  j.web_oa_t,
  (j.bas_oa_t - j.web_oa_t) AS delta_f
FROM joined j
WHERE j.web_oa_t IS NOT NULL
  AND j.web_ts IS NOT NULL
  AND EXTRACT(EPOCH FROM (j.ts - j.web_ts)) <= $6
ORDER BY j.ts DESC, j.equipment_id
LIMIT $7;
