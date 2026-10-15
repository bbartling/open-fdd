-- Soft-OPEN analytics pack: latest setpoint-like roles per equipment.
-- Parameters:
--   $1 = site_id
--   $2 = window start (timestamptz, NULL = open)
--   $3 = window end   (timestamptz, NULL = open)
--   $4 = equipment_ids (text[], NULL/empty = all)
-- Soft-OPEN ≠ FQ.
WITH ranked AS (
  SELECT
    split_part(openfdd_key, '.', 1) AS equipment_id,
    split_part(openfdd_key, '.', 2) AS role,
    ts,
    val,
    row_number() OVER (
      PARTITION BY split_part(openfdd_key, '.', 1), split_part(openfdd_key, '.', 2)
      ORDER BY ts DESC
    ) AS rn
  FROM sample
  WHERE site_id = $1
    AND ($2::timestamptz IS NULL OR ts >= $2)
    AND ($3::timestamptz IS NULL OR ts < $3)
    AND (
      $4::text[] IS NULL
      OR cardinality($4) = 0
      OR split_part(openfdd_key, '.', 1) = ANY ($4)
    )
    AND val IS NOT NULL
    AND (
      split_part(openfdd_key, '.', 2) LIKE '%_sp'
      OR split_part(openfdd_key, '.', 2) LIKE '%_setpoint'
      OR split_part(openfdd_key, '.', 2) IN (
        'sat_sp', 'dsp_sp', 'zone_t_sp', 'chw_supply_sp', 'hw_supply_sp'
      )
    )
)
SELECT equipment_id, role, ts, val AS setpoint
FROM ranked
WHERE rn = 1
ORDER BY equipment_id, role
LIMIT 2000;
