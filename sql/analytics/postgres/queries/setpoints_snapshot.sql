-- Latest setpoint per bound key.
-- Parameters:
--   $1 = site_id
--   $2 = window start (timestamptz, NULL = open)
--   $3 = window end   (timestamptz, NULL = open)
--   $4 = equipment_ids (text[], NULL/empty = all)
WITH ranked AS (
  SELECT
    a.equipment_id,
    a.role,
    a.openfdd_key,
    s.ts,
    s.val,
    row_number() OVER (
      PARTITION BY a.openfdd_key
      ORDER BY s.ts DESC
    ) AS rn
  FROM sample s
  JOIN authorized_series a
    ON a.site_id = s.site_id
   AND a.openfdd_key = s.openfdd_key
  WHERE s.site_id = $1
    AND ($2::timestamptz IS NULL OR s.ts >= $2)
    AND ($3::timestamptz IS NULL OR s.ts < $3)
    AND (
      $4::text[] IS NULL
      OR cardinality($4) = 0
      OR a.equipment_id = ANY ($4)
    )
    AND s.val IS NOT NULL
    AND (
      a.role LIKE '%_sp'
      OR a.role LIKE '%_setpoint'
      OR a.role IN (
        'sat_sp', 'dsp_sp', 'zone_t_sp', 'chw_supply_sp', 'hw_supply_sp'
      )
    )
)
SELECT equipment_id, role, openfdd_key, ts, val AS setpoint
FROM ranked
WHERE rn = 1
ORDER BY equipment_id, role, openfdd_key
LIMIT 2000;
