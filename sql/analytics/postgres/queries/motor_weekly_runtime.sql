-- Soft-OPEN analytics pack: motor weekly runtime (status/cmd rows × 300s).
-- Parameter: $1 = site_id (building_id). Adapters bind only — no equation forks.
SELECT
  split_part(openfdd_key, '.', 1) AS equipment_id,
  'motor'::text AS kind,
  'ahu'::text AS plant_group,
  date_trunc('week', ts) AS week_start,
  to_char(date_trunc('week', ts), 'IYYY-"W"IW') AS week_label,
  (COUNT(*) FILTER (WHERE COALESCE(val, 0) > 0.05)::double precision * 300.0 / 3600.0)
    AS run_hours,
  (COUNT(*) FILTER (WHERE COALESCE(val, 0) > 0.05)::double precision * 300.0 / 3600.0)
    AS runtime_hours
FROM sample
WHERE site_id = $1
  AND (openfdd_key LIKE '%.fan_status' OR openfdd_key LIKE '%.fan_cmd'
       OR openfdd_key LIKE '%.pump_status' OR openfdd_key LIKE '%.pump_cmd')
GROUP BY 1, 4
ORDER BY 1, 4
LIMIT 500;
