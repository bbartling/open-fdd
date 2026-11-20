-- Mean by UTC hour of day per point over fdd.input_sample (issue #1757, archived 4.x `diurnal`).
-- Portable SQL: PostgreSQL / TimescaleDB, DuckDB and SQLite >= 3.25 (integer arithmetic, no extensions).
-- Rendered by open_fdd.analytics.sql_point_stats.render_diurnal_sql with checked literals; {role_filter} limits the
-- roles (default: the archived list oa_t, web_oa_t, sat, mat, rat, zone_t, fan_cmd, clg_valve_pct, htg_valve_pct).
--
-- Same numbers as open_fdd.analytics.point_stats.diurnal_hourly: per point and UTC hour (0-23) of non-NULL samples in
-- the window, avg_val and n. The hour is exact integer math on epoch ms (the remainder is subtracted before dividing,
-- so integer and float division agree on every engine).
WITH src AS (
  SELECT s.point_key, p.equipment_id, p.role, {ts_ms} AS t, CAST(s.value AS DOUBLE PRECISION) AS value
  FROM fdd.input_sample s
  JOIN fdd.point p ON p.site_id = s.site_id AND p.point_key = s.point_key
  WHERE s.site_id = {site_id}{point_filter}{role_filter}
),
win AS (
  SELECT point_key, equipment_id, role, value,
         ((t % 86400000) + 86400000) % 86400000 AS ms_of_day
  FROM src WHERE 1 = 1{window_filter}
),
hourly AS (
  SELECT point_key, equipment_id, role, value,
         CAST((ms_of_day - ms_of_day % 3600000) / 3600000 AS INTEGER) AS hour_utc
  FROM win
)
SELECT point_key, equipment_id, role, hour_utc, AVG(value) AS avg_val, COUNT(*) AS n
FROM hourly
GROUP BY point_key, equipment_id, role, hour_utc
ORDER BY point_key, hour_utc
