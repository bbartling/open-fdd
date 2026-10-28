-- Generic warehouse template: implement the documented dialect hooks. Render numeric template parameters with render_rule.py.
-- Inputs must be scoped to one tenant/site and cadence; see README.md.
-- oat_meteo_fault.sql — BAS OAT vs meteo reference (|Δ| > threshold) + confirm
-- Web weather is joined as-of with WEB_ASOF_BOUND_SECONDS (cadence + margin).
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
      WHEN DATEDIFF('second', (
        SELECT d.timestamp_utc
        FROM web_dedup d
        WHERE d.timestamp_utc <= h.timestamp_utc
        ORDER BY d.timestamp_utc DESC
        LIMIT 1
      ), h.timestamp_utc) > {{WEB_ASOF_BOUND_SECONDS}}
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
lagged AS (
  SELECT
    *,
    LAG(raw_fault) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc) AS prev_raw_fault,
    LAG(assessable) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc) AS prev_assessable
  FROM base
),
grp AS (
  SELECT
    *,
    SUM(CASE
      WHEN NOT assessable
        OR (raw_fault <> prev_raw_fault OR (raw_fault IS NULL AND prev_raw_fault IS NOT NULL)
            OR (raw_fault IS NOT NULL AND prev_raw_fault IS NULL))
        OR COALESCE(prev_assessable, false) = false
      THEN 1 ELSE 0 END)
      OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS UNBOUNDED PRECEDING) AS streak_id
  FROM lagged
),
ranked AS (
  SELECT
    *,
    ROW_NUMBER() OVER (PARTITION BY equipment_id, streak_id ORDER BY timestamp_utc) AS streak_len
  FROM grp
),
final AS (
  SELECT
    equipment_id,
    CASE
      WHEN assessable AND raw_fault = 1 AND streak_len >= {{CONFIRM_ROWS}} THEN 1
      ELSE 0
    END AS confirmed
  FROM ranked
)
SELECT
  equipment_id,
  SUM(confirmed) * {{POLL_SECONDS}} / 3600.0 AS fault_hours,
  100.0 * SUM(confirmed) / NULLIF(COUNT(*), 0) AS fault_pct
FROM final
GROUP BY equipment_id;
