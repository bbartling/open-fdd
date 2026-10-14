-- Soft-OPEN analytics pack: occupancy mode samples (calendar Soft-OPEN later).
-- Parameter: $1 = site_id.
SELECT ts, openfdd_key, val,
       split_part(openfdd_key, '.', 1) AS equipment_id
FROM sample
WHERE site_id = $1 AND openfdd_key LIKE '%.occ_mode'
ORDER BY ts DESC
LIMIT 2000;
