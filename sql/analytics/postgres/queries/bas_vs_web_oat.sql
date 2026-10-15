-- Soft-OPEN analytics pack: BAS vs web outdoor-air temperature pairs.
-- Parameters:
--   $1 = site_id
--   $2 = window start (timestamptz, NULL = open)
--   $3 = window end   (timestamptz, NULL = open)
--   $4 = equipment_ids (text[], NULL/empty = all)
-- Timestamp join Soft-OPEN; exact point-map Soft-OPEN later.
WITH bas AS (
  SELECT ts, val AS bas_oa_t, split_part(openfdd_key, '.', 1) AS equipment_id
  FROM sample
  WHERE site_id = $1
    AND ($2::timestamptz IS NULL OR ts >= $2)
    AND ($3::timestamptz IS NULL OR ts < $3)
    AND (
      $4::text[] IS NULL
      OR cardinality($4) = 0
      OR split_part(openfdd_key, '.', 1) = ANY ($4)
    )
    AND openfdd_key LIKE '%.oa_t'
),
web AS (
  SELECT ts, val AS web_oa_t
  FROM sample
  WHERE site_id = $1
    AND ($2::timestamptz IS NULL OR ts >= $2)
    AND ($3::timestamptz IS NULL OR ts < $3)
    AND openfdd_key LIKE '%.web_oa_t'
)
SELECT b.ts, b.equipment_id, b.bas_oa_t, w.web_oa_t, (b.bas_oa_t - w.web_oa_t) AS delta_f
FROM bas b
JOIN web w ON w.ts = b.ts
ORDER BY b.ts DESC
LIMIT 2000;
