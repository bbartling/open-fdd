-- SV-STALE (#1673): missing data. A sensor series is stale while it has no valid sample for longer than
-- STALE_AFTER_HOURS. This rule has no value test (a stuck value that is still polled is SV-FLATLINE) and no
-- run-proof gate (data monitoring does not depend on the motor).
--
-- Expected series: `sweep_series` lists every bound series the caller fetched successfully, with its requested
-- window [window_start, window_end). A bound series with no sample at all is therefore assessed (it faults for
-- the whole window beyond STALE_AFTER_HOURS). A series the caller could not fetch is not listed and is not
-- assessed. Callers that do not fill `sweep_series` get the series present in `sensor_history`, over the
-- equipment's observed window (first to last timestamp in history and sensor_history).
--
-- Per series, the window start, every valid sample and the window end split the window into intervals. An
-- interval longer than STALE_AFTER_SECONDS contributes (interval - STALE_AFTER_SECONDS) of fault time, starting
-- STALE_AFTER_SECONDS after its first point. covered_hours is the whole window.
WITH eq_window AS (
  SELECT equipment_id, MIN(epoch_seconds) AS start_epoch, MAX(epoch_seconds) AS end_epoch
  FROM (
    SELECT equipment_id, EXTRACT(EPOCH FROM timestamp_utc) AS epoch_seconds FROM history
    UNION ALL
    SELECT equipment_id, EXTRACT(EPOCH FROM timestamp_utc) AS epoch_seconds FROM sensor_history
    WHERE sensor_role IN ({{ASSESSABLE_ROLES}})
  ) observed
  GROUP BY equipment_id
),
declared AS (
  SELECT equipment_id, series_id, MIN(sensor_role) AS sensor_role,
    MIN(EXTRACT(EPOCH FROM window_start)) AS start_epoch, MAX(EXTRACT(EPOCH FROM window_end)) AS end_epoch
  FROM sweep_series
  WHERE sensor_role IN ({{ASSESSABLE_ROLES}})
  GROUP BY equipment_id, series_id
),
observed_series AS (
  SELECT equipment_id, series_id, MIN(sensor_role) AS sensor_role
  FROM sensor_history
  WHERE sensor_role IN ({{ASSESSABLE_ROLES}})
  GROUP BY equipment_id, series_id
),
expected AS (
  SELECT equipment_id, series_id, sensor_role, start_epoch, end_epoch FROM declared
  UNION ALL
  SELECT o.equipment_id, o.series_id, o.sensor_role, w.start_epoch, w.end_epoch
  FROM observed_series o
  JOIN eq_window w ON w.equipment_id = o.equipment_id
  LEFT JOIN declared d ON d.equipment_id = o.equipment_id AND d.series_id = o.series_id
  WHERE d.series_id IS NULL
),
points AS (
  SELECT e.equipment_id, e.series_id, e.sensor_role, EXTRACT(EPOCH FROM s.timestamp_utc) AS epoch_seconds
  FROM expected e
  JOIN sensor_history s ON s.equipment_id = e.equipment_id AND s.series_id = e.series_id
  WHERE fdd.mask_sweep_val(s.sensor_role, s.unit, s.value) IS NOT NULL
    AND EXTRACT(EPOCH FROM s.timestamp_utc) >= e.start_epoch
    AND EXTRACT(EPOCH FROM s.timestamp_utc) <= e.end_epoch
  UNION ALL
  SELECT equipment_id, series_id, sensor_role, start_epoch AS epoch_seconds FROM expected
  UNION ALL
  SELECT equipment_id, series_id, sensor_role, end_epoch AS epoch_seconds FROM expected
),
steps AS (
  SELECT points.*,
    LEAD(epoch_seconds) OVER (PARTITION BY equipment_id, series_id ORDER BY epoch_seconds) AS next_epoch
  FROM points
),
intervals AS (
  SELECT equipment_id, series_id, sensor_role, epoch_seconds, next_epoch - epoch_seconds AS dt_seconds
  FROM steps
  WHERE next_epoch IS NOT NULL AND next_epoch > epoch_seconds
),
final AS (
  SELECT equipment_id, series_id, sensor_role, epoch_seconds AS segment_epoch, 0 AS confirmed,
    CASE WHEN dt_seconds > {{STALE_AFTER_SECONDS}} THEN {{STALE_AFTER_SECONDS}} ELSE dt_seconds END AS held_seconds
  FROM intervals
  UNION ALL
  SELECT equipment_id, series_id, sensor_role, epoch_seconds + {{STALE_AFTER_SECONDS}} AS segment_epoch, 1 AS confirmed,
    dt_seconds - {{STALE_AFTER_SECONDS}} AS held_seconds
  FROM intervals
  WHERE dt_seconds > {{STALE_AFTER_SECONDS}}
),
scored AS (
  SELECT equipment_id, series_id, sensor_role,
    SUM(CASE WHEN confirmed = 1 THEN held_seconds ELSE 0.0 END) / 3600.0 AS fault_hours,
    SUM(held_seconds) / 3600.0 AS covered_hours
  FROM final
  GROUP BY equipment_id, series_id, sensor_role
)
SELECT e.equipment_id, e.series_id, e.sensor_role,
  CASE WHEN COALESCE(scored.covered_hours, 0.0) > 0 THEN COALESCE(scored.fault_hours, 0.0) ELSE NULL END AS fault_hours,
  COALESCE(scored.covered_hours, 0.0) AS covered_hours
FROM expected e
LEFT JOIN scored ON scored.equipment_id = e.equipment_id AND scored.series_id = e.series_id
ORDER BY e.equipment_id, e.series_id;
