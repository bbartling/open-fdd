-- Soft-OPEN analytics pack: bounded role timeseries.
-- Parameters: $1 = site_id, $2 = role suffix pattern (e.g. '%.zone_t'), $3 = limit.
SELECT ts, openfdd_key, val,
       split_part(openfdd_key, '.', 1) AS equipment_id
FROM sample
WHERE site_id = $1 AND openfdd_key LIKE $2
ORDER BY ts DESC
LIMIT $3;
