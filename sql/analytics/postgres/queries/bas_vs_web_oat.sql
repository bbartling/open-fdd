-- Soft-OPEN analytics pack: BAS vs web outdoor-air temperature pairs.
-- Parameter: $1 = site_id. Timestamp join Soft-OPEN; exact point-map Soft-OPEN later.
WITH bas AS (
  SELECT ts, val AS bas_oa_t, split_part(openfdd_key, '.', 1) AS equipment_id
  FROM sample
  WHERE site_id = $1 AND openfdd_key LIKE '%.oa_t'
),
web AS (
  SELECT ts, val AS web_oa_t
  FROM sample
  WHERE site_id = $1 AND openfdd_key LIKE '%.web_oa_t'
)
SELECT b.ts, b.equipment_id, b.bas_oa_t, w.web_oa_t, (b.bas_oa_t - w.web_oa_t) AS delta_f
FROM bas b
JOIN web w ON w.ts = b.ts
ORDER BY b.ts DESC
LIMIT 2000;
