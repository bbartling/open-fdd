-- PostgreSQL adaptation. Render numeric template parameters with render_rule.py.
-- Inputs must be scoped to one tenant/site and cadence; see README.md.
-- oat_meteo_fault.sql — BAS OAT vs meteo reference (|Δ| > threshold) + confirm
-- Storage is SI (metric-c-v2): oa_t and the web reference are °C; OAT_ERR is a temperature difference in K.
-- Web weather is joined as-of: carry the last web sample forward up to
-- WEB_ASOF_BOUND_SECONDS (web cadence + margin from registry). Beyond that bound
-- the local sample is not compared (not-assessed seconds, never a no-fault).
-- Prefer equipment web_oa_t (matches the reference oracle); fall back to weather rows when absent.
-- Targeting is registry equipment_kinds (ahu) plus the package stamp applied
-- after this query. This file does not filter equipment_id by prefix or LIKE.
WITH web_points AS (
  SELECT timestamp_utc, web_oa_t AS ref_val
  FROM weather
  WHERE web_oa_t IS NOT NULL
  UNION ALL
  SELECT timestamp_utc, web_oa_t AS ref_val
  FROM history
  WHERE web_oa_t IS NOT NULL
),
web_dedup AS (
  SELECT timestamp_utc, MAX(ref_val) AS ref_val
  FROM web_points
  GROUP BY timestamp_utc
),
joined AS (
  SELECT
    h.equipment_id,
    h.timestamp_utc,
    h.oa_t,
    (
      SELECT d.timestamp_utc
      FROM web_dedup d
      WHERE d.timestamp_utc <= h.timestamp_utc
      ORDER BY d.timestamp_utc DESC
      LIMIT 1
    ) AS ref_ts,
    (
      SELECT d.ref_val
      FROM web_dedup d
      WHERE d.timestamp_utc <= h.timestamp_utc
      ORDER BY d.timestamp_utc DESC
      LIMIT 1
    ) AS ref_oa_t,
    CASE
      WHEN h.oa_t IS NULL THEN false
      WHEN (
        SELECT d.ref_val
        FROM web_dedup d
        WHERE d.timestamp_utc <= h.timestamp_utc
        ORDER BY d.timestamp_utc DESC
        LIMIT 1
      ) IS NULL THEN false
      WHEN EXTRACT(EPOCH FROM (
        h.timestamp_utc - (
          SELECT d.timestamp_utc
          FROM web_dedup d
          WHERE d.timestamp_utc <= h.timestamp_utc
          ORDER BY d.timestamp_utc DESC
          LIMIT 1
        )
      )) > {{WEB_ASOF_BOUND_SECONDS}}
      THEN false
      ELSE true
    END AS assessable
  FROM history h
),
base AS (
  SELECT
    equipment_id,
    timestamp_utc,
    assessable,
    CAST(CASE
      WHEN NOT assessable THEN NULL
      WHEN ABS(oa_t - ref_oa_t) > {{OAT_ERR}} THEN 1
      ELSE 0 END AS INT) AS raw_fault
  FROM joined
),
elapsed_hold AS (
  SELECT
    stepped.*,
    CASE
      WHEN NOT assessable THEN 0.0
      WHEN stepped.dt_seconds IS NULL
        OR stepped.dt_seconds <= 0.0
        OR stepped.dt_seconds > ({{MAX_GAP_HOURS}} * 3600.0)
      THEN 0.0
      ELSE stepped.dt_seconds
    END AS held_seconds,
    CASE
      WHEN stepped.dt_seconds > ({{MAX_GAP_HOURS}} * 3600.0) THEN 1
      ELSE 0
    END AS gap_after
  FROM (
    SELECT
      src.*,
      EXTRACT(EPOCH FROM (
        LEAD(src.timestamp_utc) OVER (
          PARTITION BY src.equipment_id ORDER BY src.timestamp_utc
        ) - src.timestamp_utc
      )) AS dt_seconds
    FROM base src
  ) stepped
),
lagged AS (
  SELECT
    *,
    CASE
      WHEN NOT assessable THEN 1
      WHEN raw_fault = LAG(raw_fault) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc)
       AND COALESCE(LAG(gap_after) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc), 0) = 0
       AND COALESCE(LAG(assessable) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc), false)
      THEN 0 ELSE 1
    END AS is_new_streak
  FROM elapsed_hold
),
grp AS (
  SELECT
    *,
    SUM(is_new_streak)
      OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS UNBOUNDED PRECEDING) AS streak_id
  FROM lagged
),
ranked AS (
  SELECT
    *,
    SUM(held_seconds) OVER (
      PARTITION BY equipment_id, streak_id ORDER BY timestamp_utc
      ROWS UNBOUNDED PRECEDING
    ) AS streak_elapsed
  FROM grp
),
final AS (
  SELECT
    equipment_id,
    held_seconds,
    CASE
      WHEN assessable AND raw_fault = 1 AND streak_elapsed >= {{CONFIRM_SECONDS}} THEN 1
      ELSE 0
    END AS confirmed
  FROM ranked
)
SELECT
  equipment_id,
  SUM(CASE WHEN confirmed = 1 THEN held_seconds ELSE 0.0 END) / 3600.0 AS fault_hours,
  SUM(held_seconds) / 3600.0 AS covered_hours,
  100.0 * SUM(CASE WHEN confirmed = 1 THEN held_seconds ELSE 0.0 END)
    / NULLIF(SUM(held_seconds), 0.0) AS fault_pct
FROM final
GROUP BY equipment_id;
