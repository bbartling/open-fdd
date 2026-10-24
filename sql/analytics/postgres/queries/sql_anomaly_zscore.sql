-- Event-table rolling z-score. The baseline is the previous $5 samples
-- for the same equipment and role. The current sample is not part of
-- its own mean or sample standard deviation.
--
-- A scored sample is an event when |z| >= $6. $7 false keeps every
-- flagged timestamp. $7 true keeps rising edges only. Coverage counts
-- still include the flagged samples that the edge filter omits.
--
-- Parameters:
--   $1 site_id
--   $2 window start (timestamptz, NULL = open)
--   $3 window end   (timestamptz, NULL = open, half-open)
--   $4 equipment_ids (text[], NULL/empty = all). Exact id match.
--   $5 window_rows (int)
--   $6 z_threshold (double precision)
--   $7 transition_events (boolean)
WITH keyed AS (
  SELECT
    a.equipment_id,
    a.role,
    a.openfdd_key,
    s.ts,
    s.val
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
    AND a.role IN (
      'sat', 'mat', 'rat', 'oa_t', 'web_oa_t', 'zone_t', 'dsp'
    )
),
scored AS (
  SELECT
    k.equipment_id,
    k.role,
    k.openfdd_key,
    k.ts,
    k.val,
    stats.avg_val,
    stats.stddev_val,
    abs((k.val - stats.avg_val) / stats.stddev_val) AS z_abs
  FROM keyed k
  JOIN LATERAL (
    SELECT
      avg(p.val) AS avg_val,
      stddev_samp(p.val) AS stddev_val,
      count(*)::bigint AS n_window
    FROM (
      SELECT p.val
      FROM keyed p
      WHERE p.equipment_id = k.equipment_id
        AND p.role = k.role
        AND p.openfdd_key = k.openfdd_key
        AND p.ts < k.ts
      ORDER BY p.ts DESC
      LIMIT $5::int
    ) p
  ) stats
    ON stats.n_window >= $5::int
   AND stats.stddev_val IS NOT NULL
   AND stats.stddev_val > 0
),
marked AS (
  SELECT
    equipment_id,
    role,
    ts,
    val,
    avg_val,
    stddev_val,
    z_abs,
    z_abs >= $6::double precision AS is_anomaly,
    lag(z_abs >= $6::double precision) OVER (
      PARTITION BY openfdd_key
      ORDER BY ts
    ) AS prev_anomaly
  FROM scored
),
events AS (
  SELECT
    equipment_id,
    role,
    ts,
    val,
    avg_val,
    stddev_val,
    z_abs,
    (prev_anomaly IS DISTINCT FROM true) AS transition
  FROM marked
  WHERE is_anomaly
    AND (
      $7::boolean IS NOT TRUE
      OR prev_anomaly IS DISTINCT FROM true
    )
),
counts AS (
  SELECT
    count(*)::bigint AS n_scored,
    count(*) FILTER (WHERE is_anomaly)::bigint AS n_flagged,
    count(*) FILTER (WHERE NOT is_anomaly)::bigint AS n_ok,
    (SELECT count(*)::bigint FROM events) AS n_selected
  FROM marked
)
SELECT
  c.n_scored,
  c.n_flagged,
  c.n_ok,
  c.n_selected,
  e.equipment_id,
  e.role,
  e.ts,
  e.val,
  e.avg_val,
  e.stddev_val,
  e.z_abs,
  e.transition
FROM counts c
LEFT JOIN LATERAL (
  SELECT *
  FROM events
  ORDER BY z_abs DESC, ts DESC, equipment_id, role
  LIMIT 2000
) e ON true;
