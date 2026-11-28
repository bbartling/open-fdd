-- PostgreSQL adaptation. Render numeric template parameters with render_rule.py.
-- Inputs must be scoped to one tenant/site and cadence; see README.md.
-- econ7_ok_not_economizing.sql — Economizer OK but not economizing
-- Web DB+DP: prefer equipment web_oa_*; else weather sidecar. Never BAS outdoor_air_intake_temperature.
WITH rp AS (
  -- Run proof (#1608): the input role operating_status is resolved from the model (own status, own command, feeding equipment).
  -- With the gate on and no proof bound at all, the equipment is SKIPPED: fault_hours NULL, covered_hours 0.
  SELECT equipment_id,
    CASE WHEN {{REQUIRE_RUN_PROOF}} >= 0.5 AND COUNT(operating_status) = 0 THEN 1 ELSE 0 END AS no_run_proof
  FROM history
  GROUP BY equipment_id
),
-- #1642: the weather sidecar is joined as-of, per variable: the latest web sample at or before the history row, used for at
-- most WEB_ASOF_BOUND_SECONDS (web cadence + margin; the OAT-METEO join and pandas weather_on_grid). An exact timestamp
-- join left 2 of 3 rows without weather on a 5-min grid with 15-min weather, and those rows broke confirmation.
wx_web_oa_t AS (
  SELECT timestamp_utc AS ref_ts, ref_val,
    LEAD(timestamp_utc) OVER (ORDER BY timestamp_utc) AS next_ref_ts
  FROM (
    SELECT timestamp_utc, MAX(weather_service_air_temperature) AS ref_val
    FROM weather
    WHERE weather_service_air_temperature IS NOT NULL
    GROUP BY timestamp_utc
  ) wx_web_oa_t_points
),
wx_web_oa_dp AS (
  SELECT timestamp_utc AS ref_ts, ref_val,
    LEAD(timestamp_utc) OVER (ORDER BY timestamp_utc) AS next_ref_ts
  FROM (
    SELECT timestamp_utc, MAX(weather_service_air_dew_point_temperature) AS ref_val
    FROM weather
    WHERE weather_service_air_dew_point_temperature IS NOT NULL
    GROUP BY timestamp_utc
  ) wx_web_oa_dp_points
),
h AS (
  SELECT
    operating_status,
    h.equipment_id,
    h.timestamp_utc,
    COALESCE(h.weather_service_air_temperature, wx_web_oa_t.ref_val) AS weather_service_air_temperature,
    COALESCE(h.weather_service_air_dew_point_temperature, wx_web_oa_dp.ref_val) AS weather_service_air_dew_point_temperature,
    h.outdoor_air_intake_damper_position_command AS oa_d,
    h.cooling_valve_position_command AS clg,
    -- #1642: mechanical-cooling proof candidates (pandas mechanical_proof_mask; MECH-OAT-1 uses the same selection)
    CASE WHEN h.compressor_operating_status IS NULL THEN NULL WHEN h.compressor_operating_status > 0.05 THEN 1 ELSE 0 END AS c1,
    CASE WHEN h.chiller_operating_status IS NULL THEN NULL WHEN h.chiller_operating_status > 0.05 THEN 1 ELSE 0 END AS c2,
    CASE WHEN h.chiller_electric_current IS NULL THEN NULL WHEN h.chiller_electric_current > {{MECH_AMPS_MIN}} THEN 1 ELSE 0 END AS c3,
    CASE WHEN h.chiller_electric_power IS NULL THEN NULL WHEN h.chiller_electric_power > {{MECH_POWER_KW_MIN}} THEN 1 ELSE 0 END AS c4,
    h.supply_fan_command,
    h.supply_fan_operating_status,
    CASE
      WHEN h.supply_fan_operating_status IS NOT NULL THEN CASE WHEN h.supply_fan_operating_status > 0.05 THEN 1 ELSE 0 END
      WHEN h.supply_fan_command IS NOT NULL THEN CASE WHEN h.supply_fan_command > 0.5 THEN 1 ELSE 0 END
      ELSE 1
    END AS fan_on
  FROM history h
  LEFT JOIN wx_web_oa_t
    ON h.timestamp_utc >= wx_web_oa_t.ref_ts
   AND (wx_web_oa_t.next_ref_ts IS NULL OR h.timestamp_utc < wx_web_oa_t.next_ref_ts)
   AND EXTRACT(EPOCH FROM (h.timestamp_utc - wx_web_oa_t.ref_ts)) <= {{WEB_ASOF_BOUND_SECONDS}}
  LEFT JOIN wx_web_oa_dp
    ON h.timestamp_utc >= wx_web_oa_dp.ref_ts
   AND (wx_web_oa_dp.next_ref_ts IS NULL OR h.timestamp_utc < wx_web_oa_dp.next_ref_ts)
   AND EXTRACT(EPOCH FROM (h.timestamp_utc - wx_web_oa_dp.ref_ts)) <= {{WEB_ASOF_BOUND_SECONDS}}
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
demand AS (
  -- cooling demand: the cooling valve open OR the selected mechanical-cooling proof on (pandas econ7_compute)
  SELECT h.*,
    CASE
      WHEN h.clg IS NOT NULL AND h.clg > {{CLG_OPEN_MIN}} THEN 1
      WHEN pp.proof_kind = 1 AND h.c1 = 1 THEN 1
      WHEN pp.proof_kind = 2 AND h.c2 = 1 THEN 1
      WHEN pp.proof_kind = 3 AND h.c3 = 1 THEN 1
      WHEN pp.proof_kind = 4 AND h.c4 = 1 THEN 1
      ELSE 0
    END AS cooling_demand
  FROM h
  JOIN proof_pick pp ON pp.equipment_id = h.equipment_id
),
base AS (
  SELECT
    equipment_id,
    timestamp_utc,
    CAST(CASE
      WHEN {{REQUIRE_RUN_PROOF}} >= 0.5 AND COALESCE(operating_status, 0) <= 0.05 THEN 0
      WHEN COALESCE(fan_on, 1) = 0 THEN 0
      WHEN weather_service_air_temperature IS NULL OR weather_service_air_dew_point_temperature IS NULL OR oa_d IS NULL THEN 0
      WHEN weather_service_air_temperature >= {{ECON7_DB_MIN}} AND weather_service_air_temperature < {{ECON7_DB_MAX}} AND weather_service_air_dew_point_temperature < {{ECON7_DP_MAX}}
       AND cooling_demand = 1 AND oa_d < {{ECON7_DAMPER_MIN}} THEN 1
      ELSE 0
    END AS INT) AS raw_fault,
    -- #1631: proven-on (the run-proof gate passes) time is the fault_pct denominator (active_hours)
    CASE WHEN {{REQUIRE_RUN_PROOF}} < 0.5 THEN 1 WHEN operating_status > 0.05 THEN 1 ELSE 0 END AS proof_active
  FROM demand
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
    proof_active,
    CASE WHEN raw_fault = 1 AND streak_elapsed >= {{CONFIRM_SECONDS}} THEN 1 ELSE 0 END AS confirmed
  FROM ranked
)
SELECT
  equipment_id,
  CASE WHEN (SELECT rpx.no_run_proof FROM rp rpx WHERE rpx.equipment_id = final.equipment_id) = 1 THEN NULL ELSE SUM(CASE WHEN confirmed = 1 THEN held_seconds ELSE 0.0 END) / 3600.0 END AS fault_hours,
  CASE WHEN (SELECT rpx.no_run_proof FROM rp rpx WHERE rpx.equipment_id = final.equipment_id) = 1 THEN 0.0 ELSE SUM(held_seconds) / 3600.0 END AS covered_hours,
  CASE WHEN (SELECT rpx.no_run_proof FROM rp rpx WHERE rpx.equipment_id = final.equipment_id) = 1 THEN 0.0 ELSE SUM(CASE WHEN proof_active = 1 THEN held_seconds ELSE 0.0 END) / 3600.0 END AS active_hours,
  CASE WHEN (SELECT rpx.no_run_proof FROM rp rpx WHERE rpx.equipment_id = final.equipment_id) = 1 THEN NULL ELSE COALESCE(100.0 * SUM(CASE WHEN confirmed = 1 THEN held_seconds ELSE 0.0 END) / NULLIF(SUM(CASE WHEN proof_active = 1 THEN held_seconds ELSE 0.0 END), 0.0), 0.0) END AS fault_pct
FROM final
GROUP BY equipment_id;
