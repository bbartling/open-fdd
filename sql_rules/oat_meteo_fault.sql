-- oat_meteo_fault.sql — BAS OAT vs weather reference (|Δ| > threshold) + confirm
-- LEFT JOIN + population kept over the full equipment timeline (matches Python
-- `len(d)` denominator); wx null or oa_t null → not fault, but row still counted.
-- Streak grouping uses a value-transition id (LAG != current) so streak_len is the
-- position within the current True/False run — matches pandas confirm_fault()
-- (grp on raw != raw.shift()). The previous "count of zero rows so far" id shared
-- the boundary False row with the following True run, confirming faults one row
-- early and over-counting confirmed hours.
WITH wx AS (
  SELECT timestamp_utc, oa_t AS wx_oa_t FROM weather WHERE oa_t IS NOT NULL
),
joined AS (
  SELECT
    h.equipment_id,
    h.timestamp_utc,
    h.oa_t,
    wx.wx_oa_t
  FROM history h
  LEFT JOIN wx ON h.timestamp_utc = wx.timestamp_utc
  WHERE h.equipment_id LIKE 'AHU%' OR h.equipment_id LIKE 'AHU_%'
),
base AS (
  SELECT
    equipment_id,
    timestamp_utc,
    CAST(CASE
      WHEN oa_t IS NOT NULL AND wx_oa_t IS NOT NULL AND ABS(oa_t - wx_oa_t) > {{OAT_ERR}}
      THEN 1 ELSE 0 END AS INT) AS raw_fault
  FROM joined
),
lagged AS (
  SELECT
    *,
    LAG(raw_fault) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc) AS prev_raw_fault
  FROM base
),
grp AS (
  SELECT
    *,
    SUM(CASE WHEN raw_fault IS DISTINCT FROM prev_raw_fault THEN 1 ELSE 0 END)
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
    CASE WHEN raw_fault = 1 AND streak_len >= {{CONFIRM_ROWS}} THEN 1 ELSE 0 END AS confirmed
  FROM ranked
)
SELECT
  equipment_id,
  SUM(confirmed) * {{POLL_SECONDS}} / 3600.0 AS fault_hours,
  100.0 * SUM(confirmed) / NULLIF(COUNT(*), 0) AS fault_pct
FROM final
GROUP BY equipment_id;
