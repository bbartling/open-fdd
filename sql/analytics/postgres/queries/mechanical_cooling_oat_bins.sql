-- Soft-OPEN analytics pack: mechanical cooling × OAT bins (elapsed hours).
-- Parameters:
--   $1 = site_id
--   $2 = window start (timestamptz, NULL = open)
--   $3 = window end   (timestamptz, NULL = open)
--   $4 = equipment_ids (text[], NULL/empty = all)
-- Status/cmd proof preferred over amps (amps Soft-OPEN later). Prefer web_oa_t then oa_t.
-- kind=oat_bin Soft-OPEN consumer shape.
WITH oat AS (
  SELECT ts,
    COALESCE(
      max(val) FILTER (WHERE openfdd_key LIKE '%.web_oa_t'),
      max(val) FILTER (WHERE openfdd_key LIKE '%.oa_t')
    ) AS oat_f
  FROM sample
  WHERE site_id = $1
    AND ($2::timestamptz IS NULL OR ts >= $2)
    AND ($3::timestamptz IS NULL OR ts < $3)
    AND (openfdd_key LIKE '%.web_oa_t' OR openfdd_key LIKE '%.oa_t')
  GROUP BY ts
),
comp AS (
  SELECT
    ts,
    split_part(openfdd_key, '.', 1) AS equipment_id,
    max(val) FILTER (
      WHERE openfdd_key LIKE '%.chiller_status'
         OR openfdd_key LIKE '%.compressor_status'
         OR openfdd_key LIKE '%.chiller_cmd'
         OR openfdd_key LIKE '%.compressor_cmd'
    ) AS active
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
      openfdd_key LIKE '%.chiller_status' OR openfdd_key LIKE '%.compressor_status'
      OR openfdd_key LIKE '%.chiller_cmd' OR openfdd_key LIKE '%.compressor_cmd'
    )
  GROUP BY ts, split_part(openfdd_key, '.', 1)
),
joined AS (
  SELECT c.equipment_id, c.ts, c.active, o.oat_f
  FROM comp c
  JOIN oat o ON o.ts = c.ts
  WHERE c.active IS NOT NULL AND o.oat_f IS NOT NULL
),
ordered AS (
  -- Inactive samples stay on the timeline so an active sample cannot hold
  -- across them. Only the active sample's own forward delta is credited.
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
  -- Active time is the forward delta. Gaps longer than 1 hour are unknown.
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
