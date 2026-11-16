-- Rolling z-score anomaly flags over the core sample view fdd.input_sample (issue #1649).
-- Portable SQL: PostgreSQL / TimescaleDB, DuckDB and SQLite >= 3.28 (window functions, no SQRT, no extensions).
-- Rendered by open_fdd.analytics.sql_anomaly.render_zscore_sql, which substitutes the {placeholders} with checked
-- literals (an integer window, a float threshold, a quoted site id and an optional point-key filter).
--
-- Same semantics as open_fdd.analytics.anomaly.detectors.rolling_zscore_flags applied to each point's series of
-- non-NULL samples in time order:
--   * the trailing window is the last {window} samples INCLUDING the current one;
--   * mean and sample standard deviation (n - 1) over that window;
--   * flagged when |x - mean| / stddev > {threshold}, written as (x - mean)^2 > threshold^2 * variance;
--   * a window with fewer than {window} samples, or with no spread (min = max), never flags.
-- Values are centred on the point's mean first: the z-score does not change, the sums lose less precision.
-- is_event marks false -> true edges per point (open_fdd.analytics.anomaly.detectors.dedupe_events).
--
-- The archived 4.x query (sql/analytics/postgres/queries/sql_anomaly_zscore.sql at tag v4.0.11-central) scored each
-- sample against the PREVIOUS N samples (current excluded) with >=; this port follows the pandas detector so the two
-- agree exactly, and reads the v5 SI core (fdd.point + fdd.input_sample) instead of the 4.x sample tables.
WITH src AS (
  SELECT s.point_key, p.equipment_id, p.role, s.ts, CAST(s.value AS DOUBLE PRECISION) AS value
  FROM fdd.input_sample s
  JOIN fdd.point p ON p.site_id = s.site_id AND p.point_key = s.point_key
  WHERE s.site_id = {site_id}{point_filter}
),
centered AS (
  SELECT point_key, equipment_id, role, ts, value,
         value - AVG(value) OVER (PARTITION BY point_key) AS v
  FROM src
),
win AS (
  SELECT point_key, equipment_id, role, ts, value, v,
         COUNT(v) OVER w AS n,
         SUM(v) OVER w AS s1,
         SUM(v * v) OVER w AS s2,
         MIN(v) OVER w AS vmin,
         MAX(v) OVER w AS vmax
  FROM centered
  WINDOW w AS (PARTITION BY point_key ORDER BY ts ROWS BETWEEN {window_minus_1} PRECEDING AND CURRENT ROW)
),
scored AS (
  SELECT point_key, equipment_id, role, ts, value,
         v - s1 / n AS dev,
         CASE WHEN n = {window} AND vmax > vmin THEN (s2 - s1 * s1 / n) / (n - 1) END AS var
  FROM win
),
flagged AS (
  SELECT point_key, equipment_id, role, ts, value, dev, var,
         CASE WHEN var > 0 THEN dev * dev / var END AS z2,
         CASE WHEN var > 0 AND dev * dev > {threshold} * {threshold} * var THEN 1 ELSE 0 END AS is_anomaly
  FROM scored
)
SELECT point_key, equipment_id, role, ts, value, z2, is_anomaly,
       CASE WHEN is_anomaly = 1
             AND COALESCE(LAG(is_anomaly) OVER (PARTITION BY point_key ORDER BY ts), 0) = 0
            THEN 1 ELSE 0 END AS is_event
FROM flagged
ORDER BY point_key, ts
