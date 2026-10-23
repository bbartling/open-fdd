-- Motor weekly runtime. One signal per motor family per equipment.
-- Status wins over command so fan_status and fan_cmd are not both summed
-- into the same plant_group (that doubled weekly hours).
-- Parameters:
--   $1 = site_id (building_id)
--   $2 = window start (timestamptz, NULL = open)
--   $3 = window end   (timestamptz, NULL = open)
--   $4 = equipment_ids (text[], NULL/empty = all)
-- plant_group is air | boiler | chiller.
WITH tagged AS (
  SELECT
    split_part(s.openfdd_key, '.', 1) AS equipment_id,
    s.ts,
    s.val,
    CASE
      WHEN s.openfdd_key LIKE '%.fan_status' THEN 'fan_status'
      WHEN s.openfdd_key LIKE '%.fan_cmd' THEN 'fan_cmd'
      WHEN s.openfdd_key LIKE '%.pump_status' THEN 'pump_status'
      WHEN s.openfdd_key LIKE '%.pump_cmd' THEN 'pump_cmd'
    END AS signal,
    CASE
      WHEN s.openfdd_key LIKE '%.fan_status' OR s.openfdd_key LIKE '%.fan_cmd' THEN 'fan'
      ELSE 'pump'
    END AS motor_family,
    CASE
      WHEN s.openfdd_key LIKE '%.fan_status' OR s.openfdd_key LIKE '%.pump_status' THEN 1
      ELSE 2
    END AS signal_rank,
    e.equip_type
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
    AND (
      s.openfdd_key LIKE '%.fan_status' OR s.openfdd_key LIKE '%.fan_cmd'
      OR s.openfdd_key LIKE '%.pump_status' OR s.openfdd_key LIKE '%.pump_cmd'
    )
),
preferred AS (
  SELECT equipment_id, motor_family, MIN(signal_rank) AS signal_rank
  FROM tagged
  GROUP BY 1, 2
),
chosen AS (
  SELECT t.equipment_id, t.ts, t.val, t.signal, t.motor_family, t.equip_type
  FROM tagged t
  JOIN preferred p
    ON p.equipment_id = t.equipment_id
   AND p.motor_family = t.motor_family
   AND p.signal_rank = t.signal_rank
),
ordered AS (
  SELECT
    equipment_id,
    ts,
    val,
    signal,
    equip_type,
    EXTRACT(EPOCH FROM (
      LEAD(ts) OVER (PARTITION BY equipment_id, signal ORDER BY ts) - ts
    )) AS dt_seconds
  FROM chosen
)
SELECT
  equipment_id,
  'motor'::text AS kind,
  signal,
  CASE
    WHEN signal LIKE 'fan%' THEN 'air'
    WHEN lower(coalesce(equip_type, '')) ~ '(boiler|hot.?water|hw.?plant)' THEN 'boiler'
    WHEN signal LIKE 'pump%' THEN 'chiller'
    ELSE 'air'
  END AS plant_group,
  date_trunc('week', ts) AS week_start,
  to_char(date_trunc('week', ts), 'IYYY-"W"IW') AS week_label,
  -- On-time is the forward delta. Gaps longer than 1 hour are unknown.
  (SUM(CASE
     WHEN COALESCE(val, 0) > 0.05
      AND dt_seconds > 0.0
      AND dt_seconds <= 3600.0
     THEN dt_seconds ELSE 0.0::double precision
   END) / 3600.0) AS run_hours,
  (SUM(CASE
     WHEN COALESCE(val, 0) > 0.05
      AND dt_seconds > 0.0
      AND dt_seconds <= 3600.0
     THEN dt_seconds ELSE 0.0::double precision
   END) / 3600.0) AS runtime_hours,
  -- Chosen-signal samples in the week. This is not the chart's weekly cell count.
  COUNT(*)::bigint AS n_observations,
  -- A bucket that does not span most of its week is partial. The occupancy
  -- reference stays the full schedule; the chart labels the short bucket.
  COALESCE((MAX(ts) - MIN(ts)) < interval '6 days', true) AS partial_week
FROM ordered
GROUP BY 1, 3, 4, 5, 6
ORDER BY 1, 5
LIMIT 500;
