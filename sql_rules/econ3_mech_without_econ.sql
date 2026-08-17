-- econ3_mech_without_econ.sql — Mech cooling without integrated economizer
-- Web DB+DP: prefer equipment web_oa_* (pandas); else weather sidecar (OAT-METEO join).
-- Never substitute BAS oa_t.
WITH wx AS (
  SELECT
    timestamp_utc,
    MAX(web_oa_t) AS wx_web_oa_t,
    MAX(web_oa_dp) AS wx_web_oa_dp
  FROM weather
  GROUP BY timestamp_utc
),
h AS (
  SELECT
    h.equipment_id,
    h.timestamp_utc,
    COALESCE(h.web_oa_t, wx.wx_web_oa_t) AS web_oa_t,
    COALESCE(h.web_oa_dp, wx.wx_web_oa_dp) AS web_oa_dp,
    CASE WHEN h.oa_damper_pct IS NULL THEN NULL WHEN h.oa_damper_pct > 1.0 THEN h.oa_damper_pct / 100.0 ELSE h.oa_damper_pct END AS oa_d,
    CASE WHEN h.clg_valve_pct IS NULL THEN NULL WHEN h.clg_valve_pct > 1.0 THEN h.clg_valve_pct / 100.0 ELSE h.clg_valve_pct END AS clg,
    h.fan_cmd,
    h.fan_status,
    CASE
      WHEN h.fan_status IS NOT NULL THEN CASE WHEN h.fan_status > 0.05 THEN 1 ELSE 0 END
      WHEN h.fan_cmd IS NOT NULL THEN CASE WHEN (CASE WHEN h.fan_cmd > 1.0 THEN h.fan_cmd / 100.0 ELSE h.fan_cmd END) > 0.01 THEN 1 ELSE 0 END
      ELSE 1
    END AS fan_on
  FROM history h
  LEFT JOIN wx
    ON h.timestamp_utc = wx.timestamp_utc
),
base AS (
  SELECT
    equipment_id,
    timestamp_utc,
    CAST(CASE
      WHEN COALESCE(fan_on, 1) = 0 THEN 0
      WHEN web_oa_t IS NULL OR web_oa_dp IS NULL OR oa_d IS NULL OR clg IS NULL THEN 0
      WHEN web_oa_t >= {{ECON3_DB_MIN}} AND web_oa_t < {{ECON3_DB_MAX}} AND web_oa_dp < {{ECON3_DP_MAX}}
       AND clg > 0.01 AND oa_d < {{ECON3_DAMPER_HI}} THEN 1
      ELSE 0
    END AS INT) AS raw_fault
  FROM h
),
lagged AS (
  SELECT
    *,
    CASE
      WHEN raw_fault = LAG(raw_fault) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc)
      THEN 0 ELSE 1
    END AS is_new_streak
  FROM base
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
  SUM(confirmed) * {{POLL_SECONDS}} / 3600.0 AS fault_hours
FROM final
GROUP BY equipment_id;
