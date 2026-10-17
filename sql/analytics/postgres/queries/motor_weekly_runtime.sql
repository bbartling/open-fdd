-- Soft-OPEN analytics pack: motor weekly runtime (status/cmd rows × 300s).
-- Parameters:
--   $1 = site_id (building_id)
--   $2 = window start (timestamptz, NULL = open)
--   $3 = window end   (timestamptz, NULL = open)
--   $4 = equipment_ids (text[], NULL/empty = all)
-- Adapters bind only — no equation forks.
-- plant_group matches Overview/RCx contract: air | boiler | chiller (not ahu).
SELECT
  split_part(s.openfdd_key, '.', 1) AS equipment_id,
  'motor'::text AS kind,
  CASE
    WHEN s.openfdd_key LIKE '%.fan_status' OR s.openfdd_key LIKE '%.fan_cmd'
      THEN 'air'
    WHEN lower(coalesce(e.equip_type, '')) ~ '(boiler|hot.?water|hw.?plant)'
      THEN 'boiler'
    WHEN s.openfdd_key LIKE '%.pump_status' OR s.openfdd_key LIKE '%.pump_cmd'
      THEN 'chiller'
    ELSE 'air'
  END AS plant_group,
  date_trunc('week', s.ts) AS week_start,
  to_char(date_trunc('week', s.ts), 'IYYY-"W"IW') AS week_label,
  (COUNT(*) FILTER (WHERE COALESCE(s.val, 0) > 0.05)::double precision * 300.0 / 3600.0)
    AS run_hours,
  (COUNT(*) FILTER (WHERE COALESCE(s.val, 0) > 0.05)::double precision * 300.0 / 3600.0)
    AS runtime_hours
FROM sample s
LEFT JOIN equipment e
  ON e.building_id = s.site_id
 AND e.equipment_id = split_part(s.openfdd_key, '.', 1)
WHERE s.site_id = $1
  AND ($2::timestamptz IS NULL OR s.ts >= $2)
  AND ($3::timestamptz IS NULL OR s.ts < $3)
  AND (
    $4::text[] IS NULL
    OR cardinality($4) = 0
    OR split_part(s.openfdd_key, '.', 1) = ANY ($4)
  )
  AND (s.openfdd_key LIKE '%.fan_status' OR s.openfdd_key LIKE '%.fan_cmd'
       OR s.openfdd_key LIKE '%.pump_status' OR s.openfdd_key LIKE '%.pump_cmd')
GROUP BY 1, 3, 4
ORDER BY 1, 4
LIMIT 500;
