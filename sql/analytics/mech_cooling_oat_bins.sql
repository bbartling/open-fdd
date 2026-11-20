-- Mechanical-cooling run hours by outdoor-air-temperature bin over the core sample view fdd.input_sample (issue #1649).
-- Portable SQL: PostgreSQL / TimescaleDB, DuckDB and SQLite >= 3.28 (window functions, no extensions).
-- Rendered by open_fdd.analytics.sql_mech_cooling.render_mech_bins_sql. Python builds three small inline tables from
-- bound roles and the equipment type (never from point names) and substitutes them with checked literals:
--   {candidates}  equipment_id, tier, alt, point_key, kind ('on' | 'above'), thr: the proof ladder of
--                 open_fdd.analytics.core._select_mech_cooling_proof. Within a tier, the alternatives are the roles
--                 pandas tries in order (the first one with samples is used); points that share one alt are OR'ed
--                 (compressor stages).
--   {gates}       equipment_id, point_key: heat-pump cooling-mode points, OR'ed; the proof only counts while one is on.
--   {oats}        equipment_id, point_key: the outdoor-air-temperature point of each equipment (web before BAS).
-- {ts_ms} is the engine's ts-to-epoch-ms expression; all time math is integer milliseconds.
--
-- Same semantics as open_fdd.analytics.core.mech_cooling_oat_bins (individual devices):
--   * 'on' is the run threshold on a 0-1 value (a value above 1.5 is a percent and is divided by 100): > 0.05;
--     'above' is value > thr (amps, kW);
--   * the chosen tier is the first one that is ever on in the window, else the first tier with samples;
--   * each grid time (a sample time of the chosen tier's points) owns the interval to the next grid time; an interval
--     longer than {max_gap_ms} is unknown and counts 0, and the last grid time owns 0;
--   * an ON interval with an outdoor temperature counts its hours in that temperature's bin. Bins are the SI edges of
--     open_fdd.analytics.si_thresholds.MECH_OAT_BIN_EDGES_C (bin 0 is below the first edge);
--   * valid_ms is every counted interval (on or off) and span_ms the grid's first-to-last span (pandas coverage_pct).
-- The outdoor temperature is the latest sample at or before the grid time and at most {max_gap_ms} old. pandas
-- reindexes it to the exact grid time; the two agree when the temperature is sampled at the proof's times, and differ
-- only where the temperature is missing at a proof sample (SQL carries the last reading for up to the gap limit).
-- The archived 4.x query (sql/analytics/postgres/queries/mechanical_cooling_oat_bins.sql at tag v4.0.11-central) read
-- the 4.x sample tables with a fixed status/command role list; this port follows the pandas proof ladder.
WITH cand AS (
{candidates}
),
gate AS (
{gates}
),
oatsrc AS (
{oats}
),
wsamp AS (
  SELECT s.point_key, {ts_ms} AS t, CAST(s.value AS DOUBLE PRECISION) AS value
  FROM fdd.input_sample s
  WHERE s.site_id = {site_id}
    AND (s.point_key IN (SELECT point_key FROM cand)
         OR s.point_key IN (SELECT point_key FROM gate)
         OR s.point_key IN (SELECT point_key FROM oatsrc))
),
win AS (
  SELECT point_key, t, value FROM wsamp WHERE 1 = 1{window_filter}
),
has_data AS (
  SELECT DISTINCT point_key FROM win
),
alt_pick AS (
  SELECT c.equipment_id, c.tier, MIN(c.alt) AS alt
  FROM cand c
  JOIN has_data h ON h.point_key = c.point_key
  GROUP BY c.equipment_id, c.tier
),
tier_points AS (
  SELECT c.equipment_id, c.tier, c.alt, c.point_key, c.kind, c.thr
  FROM cand c
  JOIN alt_pick a ON a.equipment_id = c.equipment_id AND a.tier = c.tier AND a.alt = c.alt
  JOIN has_data h ON h.point_key = c.point_key
),
point_on AS (
  SELECT p.equipment_id, p.tier, w.t,
         CASE WHEN p.kind = 'on'
              THEN CASE WHEN (CASE WHEN w.value > 1.5 THEN w.value / 100.0 ELSE w.value END) > 0.05 THEN 1 ELSE 0 END
              ELSE CASE WHEN w.value > p.thr THEN 1 ELSE 0 END END AS on_flag
  FROM tier_points p
  JOIN win w ON w.point_key = p.point_key
),
tier_grid AS (
  SELECT equipment_id, tier, t, MAX(on_flag) AS on_flag
  FROM point_on
  GROUP BY equipment_id, tier, t
),
gate_grid AS (
  SELECT g.equipment_id, w.t,
         MAX(CASE WHEN (CASE WHEN w.value > 1.5 THEN w.value / 100.0 ELSE w.value END) > 0.05 THEN 1 ELSE 0 END) AS g_on
  FROM gate g
  JOIN win w ON w.point_key = g.point_key
  GROUP BY g.equipment_id, w.t
),
gated AS (
  SELECT DISTINCT equipment_id FROM gate
),
tier_gated AS (
  SELECT tg.equipment_id, tg.tier, tg.t,
         CASE WHEN ge.equipment_id IS NULL THEN tg.on_flag ELSE tg.on_flag * COALESCE(gg.g_on, 0) END AS on_flag
  FROM tier_grid tg
  LEFT JOIN gated ge ON ge.equipment_id = tg.equipment_id
  LEFT JOIN gate_grid gg ON gg.equipment_id = tg.equipment_id AND gg.t = tg.t
),
tier_any AS (
  SELECT equipment_id, tier, MAX(on_flag) AS any_on
  FROM tier_gated
  GROUP BY equipment_id, tier
),
chosen AS (
  SELECT equipment_id, COALESCE(MIN(CASE WHEN any_on = 1 THEN tier END), MIN(tier)) AS tier
  FROM tier_any
  GROUP BY equipment_id
),
grid AS (
  SELECT g.equipment_id, g.t, g.on_flag,
         LEAD(g.t) OVER (PARTITION BY g.equipment_id ORDER BY g.t) - g.t AS dt_ms
  FROM tier_gated g
  JOIN chosen c ON c.equipment_id = g.equipment_id AND c.tier = g.tier
),
dur AS (
  SELECT equipment_id, t, on_flag,
         CASE WHEN dt_ms > 0 AND dt_ms <= {max_gap_ms} THEN dt_ms ELSE 0 END AS d_ms
  FROM grid
),
coverage AS (
  SELECT equipment_id, SUM(d_ms) AS valid_ms, MAX(t) - MIN(t) AS span_ms
  FROM dur
  GROUP BY equipment_id
),
oat_and_on AS (
  -- the equipment's OAT readings and its ON intervals in one time-ordered stream; a reading sorts before an interval
  -- that starts at the same time, so "at or before" holds
  SELECT os.equipment_id, o.t, 1 AS src, o.value AS oat, CAST(NULL AS BIGINT) AS d_ms
  FROM win o
  JOIN oatsrc os ON os.point_key = o.point_key
  UNION ALL
  SELECT d.equipment_id, d.t, 2 AS src, CAST(NULL AS DOUBLE PRECISION) AS oat, d.d_ms
  FROM dur d
  WHERE d.on_flag = 1 AND d.d_ms > 0
),
oat_grouped AS (
  -- each reading starts a group; the intervals after it (until the next reading) fall in that group
  SELECT equipment_id, t, src, oat, d_ms,
         COUNT(oat) OVER (PARTITION BY equipment_id ORDER BY t, src ROWS UNBOUNDED PRECEDING) AS grp
  FROM oat_and_on
),
oat_carried AS (
  SELECT equipment_id, t, src, d_ms,
         MAX(oat) OVER (PARTITION BY equipment_id, grp) AS oat,
         MAX(CASE WHEN src = 1 THEN t END) OVER (PARTITION BY equipment_id, grp) AS oat_t
  FROM oat_grouped
),
binned AS (
  SELECT equipment_id, d_ms,
         CASE {bin_cases} END AS bin
  FROM oat_carried
  WHERE src = 2 AND oat IS NOT NULL AND t - oat_t <= {max_gap_ms}
)
SELECT b.equipment_id,
       c.tier,
       a.alt,
       b.bin,
       SUM(b.d_ms) AS on_ms,
       MAX(v.valid_ms) AS valid_ms,
       MAX(v.span_ms) AS span_ms
FROM binned b
JOIN chosen c ON c.equipment_id = b.equipment_id
JOIN alt_pick a ON a.equipment_id = c.equipment_id AND a.tier = c.tier
JOIN coverage v ON v.equipment_id = b.equipment_id
GROUP BY b.equipment_id, c.tier, a.alt, b.bin
ORDER BY b.equipment_id, b.bin
