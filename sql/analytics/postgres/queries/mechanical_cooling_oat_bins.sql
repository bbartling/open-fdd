-- Mechanical cooling × OAT bins (elapsed hours).
-- Parameters:
--   $1 = site_id
--   $2 = window start (timestamptz, NULL = open)
--   $3 = window end   (timestamptz, NULL = open)
--   $4 = equipment_ids (text[], NULL/empty = all)
-- Status/cmd proof preferred over amps. Prefer one web_oa_t series, else one oa_t.
-- Two keys for one role are not maxed into the bin.
WITH unique_role AS (
  SELECT site_id, equipment_id, role, min(openfdd_key) AS openfdd_key
  FROM authorized_series
  GROUP BY site_id, equipment_id, role
  HAVING count(*) = 1
),
oat_choice AS (
  SELECT role
  FROM unique_role
  WHERE site_id = $1
    AND role IN ('web_oa_t', 'oa_t')
  GROUP BY role
  HAVING count(*) = 1
  ORDER BY CASE role WHEN 'web_oa_t' THEN 0 ELSE 1 END
  LIMIT 1
),
oat AS (
  SELECT s.ts, max(s.val) AS oat_f
  FROM sample s
  JOIN unique_role u
    ON u.site_id = s.site_id
   AND u.openfdd_key = s.openfdd_key
  JOIN oat_choice c ON c.role = u.role
  WHERE s.site_id = $1
    AND ($2::timestamptz IS NULL OR s.ts >= $2)
    AND ($3::timestamptz IS NULL OR s.ts < $3)
  GROUP BY s.ts
),
comp AS (
  SELECT
    s.ts,
    u.equipment_id,
    max(s.val) FILTER (
      WHERE u.role IN (
        'chiller_status', 'compressor_status', 'chiller_cmd', 'compressor_cmd'
      )
    ) AS active
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
      'chiller_status', 'compressor_status', 'chiller_cmd', 'compressor_cmd'
    )
  GROUP BY s.ts, u.equipment_id
),
joined AS (
  SELECT c.equipment_id, c.ts, c.active, o.oat_f
  FROM comp c
  JOIN oat o ON o.ts = c.ts
  WHERE c.active IS NOT NULL AND o.oat_f IS NOT NULL
),
ordered AS (
  SELECT
    equipment_id,
    ts,
    active,
    oat_f,
    EXTRACT(EPOCH FROM (
      LEAD(ts) OVER (PARTITION BY equipment_id ORDER BY ts) - ts
    )) AS dt_seconds
  FROM joined
)
SELECT
  'oat_bin'::text AS kind,
  equipment_id,
  CASE
    WHEN oat_f < 50 THEN '<50'
    WHEN oat_f < 60 THEN '50-60'
    WHEN oat_f < 70 THEN '60-70'
    WHEN oat_f < 80 THEN '70-80'
    WHEN oat_f < 90 THEN '80-90'
    ELSE '>=90'
  END AS oat_bin,
  (SUM(CASE
     WHEN COALESCE(active, 0) > 0.05
      AND dt_seconds > 0.0
      AND dt_seconds <= 3600.0
     THEN dt_seconds
     ELSE 0.0::double precision
   END) / 3600.0) AS run_hours
FROM ordered
WHERE COALESCE(active, 0) > 0.05
GROUP BY 1, 2, 3
ORDER BY equipment_id, oat_bin
LIMIT 500;
