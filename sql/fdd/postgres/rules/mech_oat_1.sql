-- PostgreSQL adaptation. Render numeric template parameters with render_rule.py.
-- Inputs must be scoped to one tenant/site and cadence; see README.md.
-- mech_oat_1.sql — Mechanical cooling below 15.6 °C web OAT
-- Proof (#1642, pandas mechanical_proof_mask / mech_cooling_run_mask): compressor or chiller operation, never a cooling
-- valve alone. Candidates in order: compressor_operating_status, chiller_operating_status, chiller_electric_current > MECH_AMPS_MIN (5 A), chiller_electric_power > MECH_POWER_KW_MIN (1 kW). Per
-- equipment the first candidate that is ever on is the proof (else the first one bound, which stays off); with none bound
-- there is no proof and no fault. Web dry bulb: the equipment's weather_service_air_temperature, else the weather sidecar joined as-of (latest
-- sample at or before the row, at most WEB_ASOF_BOUND_SECONDS old, as pandas weather_on_grid). Never BAS outdoor_air_intake_temperature.
WITH wx_web_oa_t AS (
  SELECT timestamp_utc AS ref_ts, ref_val,
    LEAD(timestamp_utc) OVER (ORDER BY timestamp_utc) AS next_ref_ts
  FROM (
    SELECT timestamp_utc, MAX(weather_service_air_temperature) AS ref_val
    FROM weather
    WHERE weather_service_air_temperature IS NOT NULL
    GROUP BY timestamp_utc
  ) wx_web_oa_t_points
),
h AS (
  SELECT
    h.equipment_id,
    h.timestamp_utc,
    COALESCE(h.weather_service_air_temperature, wx_web_oa_t.ref_val) AS weather_service_air_temperature,
    CASE WHEN h.compressor_operating_status IS NULL THEN NULL WHEN h.compressor_operating_status > 0.05 THEN 1 ELSE 0 END AS c1,
    CASE WHEN h.chiller_operating_status IS NULL THEN NULL WHEN h.chiller_operating_status > 0.05 THEN 1 ELSE 0 END AS c2,
    CASE WHEN h.chiller_electric_current IS NULL THEN NULL WHEN h.chiller_electric_current > {{MECH_AMPS_MIN}} THEN 1 ELSE 0 END AS c3,
    CASE WHEN h.chiller_electric_power IS NULL THEN NULL WHEN h.chiller_electric_power > {{MECH_POWER_KW_MIN}} THEN 1 ELSE 0 END AS c4
  FROM history h
  LEFT JOIN wx_web_oa_t
    ON h.timestamp_utc >= wx_web_oa_t.ref_ts
   AND (wx_web_oa_t.next_ref_ts IS NULL OR h.timestamp_utc < wx_web_oa_t.next_ref_ts)
   AND EXTRACT(EPOCH FROM (h.timestamp_utc - wx_web_oa_t.ref_ts)) <= {{WEB_ASOF_BOUND_SECONDS}}
),
proof_pick AS (
  SELECT equipment_id,
    CASE
      WHEN MAX(c1) = 1 THEN 1 WHEN MAX(c2) = 1 THEN 2 WHEN MAX(c3) = 1 THEN 3 WHEN MAX(c4) = 1 THEN 4
      WHEN COUNT(c1) > 0 THEN 1 WHEN COUNT(c2) > 0 THEN 2 WHEN COUNT(c3) > 0 THEN 3 WHEN COUNT(c4) > 0 THEN 4
      ELSE 0
    END AS proof_kind
  FROM h
  GROUP BY equipment_id
),
base AS (
  SELECT
    h.equipment_id,
    h.timestamp_utc,
    CAST(CASE
      WHEN h.weather_service_air_temperature IS NULL THEN 0
      WHEN h.weather_service_air_temperature >= {{MECH_OAT_MAX}} THEN 0
      WHEN pp.proof_kind = 1 AND h.c1 = 1 THEN 1
      WHEN pp.proof_kind = 2 AND h.c2 = 1 THEN 1
      WHEN pp.proof_kind = 3 AND h.c3 = 1 THEN 1
      WHEN pp.proof_kind = 4 AND h.c4 = 1 THEN 1
      ELSE 0
    END AS INT) AS raw_fault
  FROM h
  JOIN proof_pick pp ON pp.equipment_id = h.equipment_id
),
elapsed_hold AS (
  -- Forward sample-and-hold. A gap longer than MAX_GAP_HOURS is unknown:
  -- it is not fault time, not covered time, and it breaks confirmation.
  -- The last sample has no forward interval.
  SELECT
    stepped.*,
    CASE
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
      WHEN raw_fault = LAG(raw_fault) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc)
       AND COALESCE(LAG(gap_after) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc), 0) = 0
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
    CASE WHEN raw_fault = 1 AND streak_elapsed >= {{CONFIRM_SECONDS}} THEN 1 ELSE 0 END AS confirmed
  FROM ranked
)
SELECT
  equipment_id,
  SUM(CASE WHEN confirmed = 1 THEN held_seconds ELSE 0.0 END) / 3600.0 AS fault_hours,
  SUM(held_seconds) / 3600.0 AS covered_hours,
  100.0 * SUM(CASE WHEN confirmed = 1 THEN held_seconds ELSE 0.0 END) / NULLIF(SUM(held_seconds), 0.0) AS fault_pct
FROM final
GROUP BY equipment_id;
