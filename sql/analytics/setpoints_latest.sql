-- Latest value per setpoint point over fdd.input_sample (issue #1757, archived 4.x `setpoints`).
-- Portable SQL: PostgreSQL / TimescaleDB, DuckDB and SQLite >= 3.25 (window functions, no extensions).
-- Rendered by open_fdd.analytics.sql_point_stats.render_setpoints_sql with checked literals; {role_filter} is the
-- setpoint roles (default: every role in sql/fdd/role_map.json ending in _sp or _setpoint, listed exactly, never LIKE).
--
-- Same rows as open_fdd.analytics.point_stats.latest_setpoints: per point, the last non-NULL sample in the window
-- (t = epoch ms, value; a tie at the same time keeps the larger value). Two points of one role stay separate rows.
WITH src AS (
  SELECT s.point_key, p.equipment_id, p.role, {ts_ms} AS t, CAST(s.value AS DOUBLE PRECISION) AS value
  FROM fdd.input_sample s
  JOIN fdd.point p ON p.site_id = s.site_id AND p.point_key = s.point_key
  WHERE s.site_id = {site_id}{point_filter}{role_filter}
),
ranked AS (
  SELECT point_key, equipment_id, role, t, value,
         ROW_NUMBER() OVER (PARTITION BY point_key ORDER BY t DESC, value DESC) AS rn
  FROM src WHERE 1 = 1{window_filter}
)
SELECT point_key, equipment_id, role, t, value
FROM ranked
WHERE rn = 1
ORDER BY point_key
