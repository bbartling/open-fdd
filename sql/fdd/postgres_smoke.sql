-- Disposable PostgreSQL smoke test. Run psql -v ON_ERROR_STOP=1 -f postgres_smoke.sql
BEGIN;
SET LOCAL TIME ZONE 'UTC';
-- Install once on PostgreSQL in a schema controlled by the application owner.
CREATE SCHEMA IF NOT EXISTS fdd;
CREATE OR REPLACE FUNCTION fdd.try_double(value text)
RETURNS double precision
LANGUAGE plpgsql IMMUTABLE STRICT PARALLEL SAFE
AS $$
BEGIN
  RETURN trim(value)::double precision;
EXCEPTION
  WHEN invalid_text_representation OR numeric_value_out_of_range THEN RETURN NULL;
END;
$$;

-- Scratch input contract only. Do not execute against production without designing adapters.
CREATE TEMP TABLE history(equipment_id VARCHAR, timestamp_utc timestamp with time zone, "ahu_sat" DOUBLE PRECISION, "building_ahu_load_satisfied" DOUBLE PRECISION, "building_zone_load_satisfied" DOUBLE PRECISION, "chiller_amps" DOUBLE PRECISION, "chiller_cmd" DOUBLE PRECISION, "chiller_current" DOUBLE PRECISION, "chiller_power" DOUBLE PRECISION, "chiller_status" DOUBLE PRECISION, "chw_dp" DOUBLE PRECISION, "chw_dp_sp" DOUBLE PRECISION, "chw_flow" DOUBLE PRECISION, "chw_pump_cmd" DOUBLE PRECISION, "chw_pump_status" DOUBLE PRECISION, "chw_reset_request_sum" DOUBLE PRECISION, "chw_return_t" DOUBLE PRECISION, "chw_supply_sp" DOUBLE PRECISION, "chw_supply_t" DOUBLE PRECISION, "clg_available" DOUBLE PRECISION, "clg_valve_pct" DOUBLE PRECISION, "compressor_status" DOUBLE PRECISION, "cooling_coil_entering_temp" DOUBLE PRECISION, "cooling_coil_leaving_temp" DOUBLE PRECISION, "cooling_sp" DOUBLE PRECISION, "cw_supply_t" DOUBLE PRECISION, "damper_cmd" DOUBLE PRECISION, "damper_pct" DOUBLE PRECISION, "duct_static" DOUBLE PRECISION, "duct_static_sp" DOUBLE PRECISION, "electric_kw" DOUBLE PRECISION, "electric_kwh" DOUBLE PRECISION, "fan_cmd" DOUBLE PRECISION, "fan_status" DOUBLE PRECISION, "heating_coil_entering_temp" DOUBLE PRECISION, "heating_coil_leaving_temp" DOUBLE PRECISION, "heating_sp" DOUBLE PRECISION, "htg_valve_pct" DOUBLE PRECISION, "hw_reset_request_sum" DOUBLE PRECISION, "hw_return_t" DOUBLE PRECISION, "hw_supply_t" DOUBLE PRECISION, "kwh" DOUBLE PRECISION, "loop_enabled" DOUBLE PRECISION, "mat" DOUBLE PRECISION, "min_flow_sp" DOUBLE PRECISION, "oa_damper_pct" DOUBLE PRECISION, "oa_h" DOUBLE PRECISION, "oa_t" DOUBLE PRECISION, "occ_mode" VARCHAR, "preheat_leave_t" DOUBLE PRECISION, "pump_status" DOUBLE PRECISION, "rat" DOUBLE PRECISION, "reheat_valve_pct" DOUBLE PRECISION, "sat" DOUBLE PRECISION, "sat_sp" DOUBLE PRECISION, "static_reset_request" DOUBLE PRECISION, "tower_fan_cmd" DOUBLE PRECISION, "vav_discharge_t" DOUBLE PRECISION, "vav_inlet_t" DOUBLE PRECISION, "vav_total_flow" DOUBLE PRECISION, "web_oa_dp" DOUBLE PRECISION, "web_oa_t" DOUBLE PRECISION, "web_wb_t" DOUBLE PRECISION, "zone_air_temp_sp" DOUBLE PRECISION, "zone_co2" DOUBLE PRECISION, "zone_flow" DOUBLE PRECISION, "zone_t" DOUBLE PRECISION);
CREATE TEMP TABLE weather(timestamp_utc timestamp with time zone, oa_t double precision, web_oa_t double precision, web_oa_dp double precision);
CREATE TEMP TABLE utility_interval(timestamp_utc timestamp with time zone, kwh double precision);
CREATE TEMP TABLE utility_monthly(billing_period varchar, kwh double precision);

-- FAN-RUNTIME-HOURS
PREPARE fdd_rule_0 AS
-- PostgreSQL adaptation. Render numeric template parameters with render_rule.py.
-- Inputs must be scoped to one tenant/site and cadence; see README.md.
-- fan_runtime_hours.sql
-- Fan runtime hours: fan_cmd normalized > 0.05
-- Output: equipment_id, fan_runtime_hours, total_hours

WITH h AS (
  SELECT
    equipment_id,
    CASE WHEN fan_cmd IS NULL THEN NULL WHEN fan_cmd > 1.0 THEN fan_cmd / 100.0 ELSE fan_cmd END AS fan_cmd
  FROM history
)
SELECT
  equipment_id,
  SUM(CASE WHEN fan_cmd > 0.05 THEN 1 ELSE 0 END) * 300 / 3600.0 AS fan_runtime_hours,
  COUNT(*) * 300 / 3600.0 AS total_hours
FROM h
WHERE fan_cmd IS NOT NULL
GROUP BY equipment_id;

EXECUTE fdd_rule_0;
DEALLOCATE fdd_rule_0;

-- VAV-1
PREPARE fdd_rule_1 AS
-- PostgreSQL adaptation. Render numeric template parameters with render_rule.py.
-- Inputs must be scoped to one tenant/site and cadence; see README.md.
-- vav1_comfort_fault.sql — zone comfort band with confirm window (Open-FDD parity)
-- When occ_mode is present, require_occupied (default 1) scores the band only
-- while occupied. The rule runner fills a missing or blank occ_mode from the
-- saved Overview calendar (session occupancy_schedule). NULL occ_mode means
-- neither a BAS occupied point nor that calendar is set. Unoccupied setback
-- stays on VAV-2.
-- OFDD-065: do not reference fan_cmd here. Zone-only parquet schemas
-- often lack fan_cmd; DataFusion then schema-errors → SKIPPED_MISSING_ROLES.
WITH h AS (
  SELECT
    equipment_id,
    timestamp_utc,
    zone_t,
    occ_mode,
    CAST(CASE WHEN zone_t < 70 OR zone_t > 75 THEN 1 ELSE 0 END AS INT) AS band_fault
  FROM history
  WHERE zone_t IS NOT NULL
),
base AS (
  SELECT
    equipment_id,
    timestamp_utc,
    CAST(CASE
      WHEN 1 >= 0.5
       AND occ_mode IS NOT NULL
       AND (
         LOWER(trim(CAST(occ_mode AS VARCHAR))) IN
           ('unoccupied','unocc','off','false','night','standby','setback','no')
         OR (
           fdd.try_double(trim(CAST(occ_mode AS VARCHAR))) IS NOT NULL
           AND fdd.try_double(trim(CAST(occ_mode AS VARCHAR))) <= 0.05
         )
       )
      THEN 0
      ELSE band_fault
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
    timestamp_utc,
    CASE WHEN raw_fault = 1 AND streak_len >= 3 THEN 1 ELSE 0 END AS confirmed
  FROM ranked
)
SELECT
  equipment_id,
  SUM(confirmed) * 300 / 3600.0 AS fault_hours,
  100.0 * SUM(confirmed) / COUNT(*) AS fault_pct
FROM final
GROUP BY equipment_id;

EXECUTE fdd_rule_1;
DEALLOCATE fdd_rule_1;

-- VAV-2
PREPARE fdd_rule_2 AS
-- PostgreSQL adaptation. Render numeric template parameters with render_rule.py.
-- Inputs must be scoped to one tenant/site and cadence; see README.md.
-- vav2_night_setback.sql — unoccupied zone stays above heating setback
-- Occupied hours do not latch. Missing occ_mode → no unoccupied proof (no fault).
WITH h AS (
  SELECT
    equipment_id,
    timestamp_utc,
    zone_t,
    occ_mode,
    CAST(CASE
      WHEN occ_mode IS NULL THEN 0
      WHEN (
        LOWER(trim(CAST(occ_mode AS VARCHAR))) IN
          ('unoccupied','unocc','off','false','night','standby','setback','0','0.0','no')
        OR (
          fdd.try_double(trim(CAST(occ_mode AS VARCHAR))) IS NOT NULL
          AND fdd.try_double(trim(CAST(occ_mode AS VARCHAR))) <= 0.05
        )
      )
       AND zone_t IS NOT NULL AND zone_t > 68 THEN 1
      ELSE 0
    END AS INT) AS raw_fault
  FROM history
),
lagged AS (
  SELECT
    *,
    CASE
      WHEN raw_fault = LAG(raw_fault) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc)
      THEN 0 ELSE 1
    END AS is_new_streak
  FROM h
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
    CASE WHEN raw_fault = 1 AND streak_len >= 3 THEN 1 ELSE 0 END AS confirmed
  FROM ranked
)
SELECT
  equipment_id,
  SUM(confirmed) * 300 / 3600.0 AS fault_hours
FROM final
GROUP BY equipment_id;

EXECUTE fdd_rule_2;
DEALLOCATE fdd_rule_2;

-- AVG-ZONE-TEMP
PREPARE fdd_rule_3 AS
-- PostgreSQL adaptation. Render numeric template parameters with render_rule.py.
-- Inputs must be scoped to one tenant/site and cadence; see README.md.
-- avg_zone_temp.sql
SELECT
  equipment_id,
  AVG(zone_t) AS avg_zone_temp,
  MIN(zone_t) AS min_zone_temp,
  MAX(zone_t) AS max_zone_temp
FROM history
WHERE zone_t IS NOT NULL
GROUP BY equipment_id;

EXECUTE fdd_rule_3;
DEALLOCATE fdd_rule_3;

-- ZONE-COMFORT-PCT
PREPARE fdd_rule_4 AS
-- PostgreSQL adaptation. Render numeric template parameters with render_rule.py.
-- Inputs must be scoped to one tenant/site and cadence; see README.md.
-- zone_comfort_pct.sql
SELECT
  equipment_id,
  100.0 * SUM(CASE WHEN zone_t >= 68 AND zone_t <= 76 THEN 1 ELSE 0 END) / COUNT(*) AS comfort_pct
FROM history
WHERE zone_t IS NOT NULL
GROUP BY equipment_id;

EXECUTE fdd_rule_4;
DEALLOCATE fdd_rule_4;

-- FAULT-ELAPSED-HOURS
PREPARE fdd_rule_5 AS
-- PostgreSQL adaptation. Render numeric template parameters with render_rule.py.
-- Inputs must be scoped to one tenant/site and cadence; see README.md.
-- fault_elapsed_hours.sql — comfort fault sample rollup
SELECT
  equipment_id,
  SUM(CASE WHEN zone_t < 68.0 OR zone_t > 76.0 THEN 1 ELSE 0 END) AS fault_samples,
  SUM(CASE WHEN zone_t < 68 OR zone_t > 76 THEN 1 ELSE 0 END) * 300 / 3600.0 AS fault_hours
FROM history
WHERE zone_t IS NOT NULL
GROUP BY equipment_id;

EXECUTE fdd_rule_5;
DEALLOCATE fdd_rule_5;

-- OAT-METEO
PREPARE fdd_rule_6 AS
-- PostgreSQL adaptation. Render numeric template parameters with render_rule.py.
-- Inputs must be scoped to one tenant/site and cadence; see README.md.
-- oat_meteo_fault.sql — BAS OAT vs meteo reference (|Δ| > threshold) + confirm
-- Prefer equipment web_oa_t (pandas); fall back to a weather join only when the
-- equipment has no web reference. `weather` may resolve to a view spanning
-- several weather equipment rows, so collapse it to one row per timestamp first —
-- otherwise the join fans out and multiplies fault_hours.
-- Targeting is registry equipment_kinds (ahu) plus the package stamp applied
-- after this query. This file does not filter equipment_id by prefix or LIKE.
WITH wx AS (
  SELECT timestamp_utc, MAX(oa_t) AS wx_oa_t
  FROM weather
  WHERE oa_t IS NOT NULL
  GROUP BY timestamp_utc
),
joined AS (
  SELECT
    h.equipment_id,
    h.timestamp_utc,
    h.oa_t,
    COALESCE(h.web_oa_t, wx.wx_oa_t) AS ref_oa_t
  FROM history h
  LEFT JOIN wx
    ON h.timestamp_utc = wx.timestamp_utc
   AND h.web_oa_t IS NULL
),
base AS (
  SELECT
    equipment_id,
    timestamp_utc,
    CAST(CASE
      WHEN oa_t IS NOT NULL AND ref_oa_t IS NOT NULL AND ABS(oa_t - ref_oa_t) > 5
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
    CASE WHEN raw_fault = 1 AND streak_len >= 3 THEN 1 ELSE 0 END AS confirmed
  FROM ranked
)
SELECT
  equipment_id,
  SUM(confirmed) * 300 / 3600.0 AS fault_hours,
  100.0 * SUM(confirmed) / NULLIF(COUNT(*), 0) AS fault_pct
FROM final
GROUP BY equipment_id;

EXECUTE fdd_rule_6;
DEALLOCATE fdd_rule_6;

-- FC13-SAT-HIGH
PREPARE fdd_rule_7 AS
-- PostgreSQL adaptation. Render numeric template parameters with render_rule.py.
-- Inputs must be scoped to one tenant/site and cadence; see README.md.
-- sat_high_fault.sql — FC13 SAT above SP at full cooling + confirm (matches cookbook fc13)
WITH h AS (
  SELECT
    equipment_id,
    timestamp_utc,
    sat,
    sat_sp,
    COALESCE(CASE WHEN clg_valve_pct IS NULL THEN NULL WHEN clg_valve_pct > 1.0 THEN clg_valve_pct / 100.0 ELSE clg_valve_pct END, 0.0) AS clg_valve_pct,
    COALESCE(CASE WHEN oa_damper_pct IS NULL THEN NULL WHEN oa_damper_pct > 1.0 THEN oa_damper_pct / 100.0 ELSE oa_damper_pct END, 0.0) AS oa_damper_pct,
    fan_cmd,
    fan_status,
        CASE
      WHEN 1 < 0.5 THEN 1
      WHEN fan_status IS NOT NULL THEN CASE WHEN fan_status > 0.05 THEN 1 ELSE 0 END
      WHEN fan_cmd IS NOT NULL THEN CASE WHEN (CASE WHEN fan_cmd > 1.0 THEN fan_cmd / 100.0 ELSE fan_cmd END) > 0.01 THEN 1 ELSE 0 END
      ELSE 1
    END AS fan_on

  FROM history
),
base AS (
  SELECT
    equipment_id,
    timestamp_utc,
    CAST(CASE
      WHEN COALESCE(fan_on, 1) = 0 THEN 0
      WHEN COALESCE(mode_stable, 1) = 0 THEN 0
      WHEN sat IS NOT NULL AND sat_sp IS NOT NULL
       AND clg_valve_pct > 0.9
       AND sat > sat_sp + 1.15
       AND (oa_damper_pct <= 0.05 OR oa_damper_pct > 0.9)
      THEN 1 ELSE 0 END AS INT) AS raw_fault
  FROM (
  SELECT h.*,
    CASE
      WHEN COALESCE(fan_on, 1) = 0 THEN 0
      WHEN SUM(CASE WHEN COALESCE(fan_on, 1) = 0 THEN 1 ELSE 0 END) OVER (
        PARTITION BY equipment_id ORDER BY timestamp_utc
        ROWS BETWEEN 1 PRECEDING AND CURRENT ROW
      ) = 0 THEN 1
      ELSE 0
    END AS mode_stable
  FROM h
) h
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
    CASE WHEN raw_fault = 1 AND streak_len >= 2 THEN 1 ELSE 0 END AS confirmed
  FROM ranked
)
, cov AS (
  SELECT equipment_id,
    100.0 * AVG(CAST(COALESCE(fan_on, 1) AS DOUBLE PRECISION)) AS cov_pct
  FROM h
  GROUP BY equipment_id
)
SELECT
  f.equipment_id,
  CASE
    WHEN 1 < 0.5 THEN SUM(f.confirmed) * 300 / 3600.0
    WHEN MAX(c.cov_pct) < 5 THEN 0.0
    ELSE SUM(f.confirmed) * 300 / 3600.0
  END AS fault_hours
FROM final f
LEFT JOIN cov c ON f.equipment_id = c.equipment_id
GROUP BY f.equipment_id;

EXECUTE fdd_rule_7;
DEALLOCATE fdd_rule_7;

-- ECON-2
PREPARE fdd_rule_8 AS
-- PostgreSQL adaptation. Render numeric template parameters with render_rule.py.
-- Inputs must be scoped to one tenant/site and cadence; see README.md.
-- economizer_fault.sql — ECON-2 economizing when outdoor unfavorable + confirm
-- CAST DOUBLE + percent gate >= 1.5 (not > 1.0) so Utf8/int 0–100 (B100 min OA 20)
-- becomes 0.20 and does not fire vs ECON2_DAMPER 0.42. Fraction 0–1 stays 0–1.
-- Pandas econ2 has no fan gate.
WITH base AS (
  SELECT
    equipment_id,
    timestamp_utc,
    CAST(CASE
      WHEN oa_t IS NOT NULL AND oa_damper_pct IS NOT NULL
       AND CAST(oa_t AS DOUBLE PRECISION) > 63
       AND (
         CASE
           WHEN CAST(oa_damper_pct AS DOUBLE PRECISION) >= 1.5
           THEN CAST(oa_damper_pct AS DOUBLE PRECISION) / 100.0
           ELSE CAST(oa_damper_pct AS DOUBLE PRECISION)
         END
       ) > 0.42
      THEN 1 ELSE 0 END AS INT) AS raw_fault
  FROM history
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
    CASE WHEN raw_fault = 1 AND streak_len >= 1 THEN 1 ELSE 0 END AS confirmed
  FROM ranked
)
SELECT
  equipment_id,
  SUM(confirmed) * 300 / 3600.0 AS fault_hours
FROM final
GROUP BY equipment_id;

EXECUTE fdd_rule_8;
DEALLOCATE fdd_rule_8;

-- FC1
PREPARE fdd_rule_9 AS
-- PostgreSQL adaptation. Render numeric template parameters with render_rule.py.
-- Inputs must be scoped to one tenant/site and cadence; see README.md.
-- fc1_duct_static_low.sql — FC1 duct static below SP at full fan + confirm
WITH h AS (
  SELECT
    equipment_id,
    timestamp_utc,
    duct_static,
    duct_static_sp,
    CASE WHEN fan_cmd IS NULL THEN NULL WHEN fan_cmd > 1.0 THEN fan_cmd / 100.0 ELSE fan_cmd END AS fan_cmd,
        CASE
      WHEN 1 < 0.5 THEN 1
      WHEN fan_status IS NOT NULL THEN CASE WHEN fan_status > 0.05 THEN 1 ELSE 0 END
      WHEN fan_cmd IS NOT NULL THEN CASE WHEN (CASE WHEN fan_cmd > 1.0 THEN fan_cmd / 100.0 ELSE fan_cmd END) > 0.01 THEN 1 ELSE 0 END
      ELSE 1
    END AS fan_on,
    -- Match pandas cookbook `_fan()`: prefer fan_status for the "full fan" gate.
    -- Synth-59 AHU_CASE_FC1 has status=1 with cmd=0.6 for most fault hours;
    -- cmd-only gating under-counts (1h vs 40h).
    CASE
      WHEN fan_status IS NOT NULL THEN CASE WHEN fan_status > 0.05 THEN 1.0 ELSE 0.0 END
      ELSE CASE WHEN fan_cmd IS NULL THEN NULL WHEN fan_cmd > 1.0 THEN fan_cmd / 100.0 ELSE fan_cmd END
    END AS fan_for_hi
  FROM history
),
base AS (
  SELECT
    equipment_id,
    timestamp_utc,
    CAST(CASE
      WHEN COALESCE(fan_on, 1) = 0 THEN 0
      WHEN COALESCE(mode_stable, 1) = 0 THEN 0
      WHEN duct_static IS NOT NULL AND duct_static_sp IS NOT NULL
       AND duct_static < duct_static_sp - 0.12
       AND fan_for_hi >= 1.0 - 0.13
      THEN 1 ELSE 0 END AS INT) AS raw_fault
  FROM (
  SELECT h.*,
    CASE
      WHEN COALESCE(fan_on, 1) = 0 THEN 0
      WHEN SUM(CASE WHEN COALESCE(fan_on, 1) = 0 THEN 1 ELSE 0 END) OVER (
        PARTITION BY equipment_id ORDER BY timestamp_utc
        ROWS BETWEEN 1 PRECEDING AND CURRENT ROW
      ) = 0 THEN 1
      ELSE 0
    END AS mode_stable
  FROM h
) h
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
    CASE WHEN raw_fault = 1 AND streak_len >= 1 THEN 1 ELSE 0 END AS confirmed
  FROM ranked
)
, cov AS (
  SELECT equipment_id,
    100.0 * AVG(CAST(COALESCE(fan_on, 1) AS DOUBLE PRECISION)) AS cov_pct
  FROM h
  GROUP BY equipment_id
)
SELECT
  f.equipment_id,
  CASE
    WHEN 1 < 0.5 THEN SUM(f.confirmed) * 300 / 3600.0
    WHEN MAX(c.cov_pct) < 5 THEN 0.0
    ELSE SUM(f.confirmed) * 300 / 3600.0
  END AS fault_hours
FROM final f
LEFT JOIN cov c ON f.equipment_id = c.equipment_id
GROUP BY f.equipment_id;

EXECUTE fdd_rule_9;
DEALLOCATE fdd_rule_9;

-- FC2
PREPARE fdd_rule_10 AS
-- PostgreSQL adaptation. Render numeric template parameters with render_rule.py.
-- Inputs must be scoped to one tenant/site and cadence; see README.md.
-- fc2_mat_low.sql — FC2 mixed air below envelope + confirm (600s default)
WITH h AS (
  SELECT
    equipment_id,
    timestamp_utc,
    mat,
    oa_t,
    rat,
    COALESCE(CASE WHEN fan_cmd IS NULL THEN 0.0 WHEN fan_cmd > 1.0 THEN fan_cmd / 100.0 ELSE fan_cmd END, 0.0) AS fan,
        CASE
      WHEN 1 < 0.5 THEN 1
      WHEN fan_status IS NOT NULL THEN CASE WHEN fan_status > 0.05 THEN 1 ELSE 0 END
      WHEN fan_cmd IS NOT NULL THEN CASE WHEN (CASE WHEN fan_cmd > 1.0 THEN fan_cmd / 100.0 ELSE fan_cmd END) > 0.01 THEN 1 ELSE 0 END
      ELSE 1
    END AS fan_on

  FROM history
),
base AS (
  SELECT
    equipment_id,
    timestamp_utc,
    CAST(CASE
      WHEN COALESCE(fan_on, 1) = 0 THEN 0
      WHEN COALESCE(mode_stable, 1) = 0 THEN 0
      WHEN mat IS NOT NULL AND oa_t IS NOT NULL AND rat IS NOT NULL
       AND (mat + 1.15) < (CASE WHEN rat < oa_t THEN rat - 1.15 ELSE oa_t - 1.15 END)
      THEN 1 ELSE 0 END AS INT) AS raw_fault
  FROM (
  SELECT h.*,
    CASE
      WHEN COALESCE(fan_on, 1) = 0 THEN 0
      WHEN SUM(CASE WHEN COALESCE(fan_on, 1) = 0 THEN 1 ELSE 0 END) OVER (
        PARTITION BY equipment_id ORDER BY timestamp_utc
        ROWS BETWEEN 1 PRECEDING AND CURRENT ROW
      ) = 0 THEN 1
      ELSE 0
    END AS mode_stable
  FROM h
) h
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
    CASE WHEN raw_fault = 1 AND streak_len >= 2 THEN 1 ELSE 0 END AS confirmed
  FROM ranked
)
, cov AS (
  SELECT equipment_id,
    100.0 * AVG(CAST(COALESCE(fan_on, 1) AS DOUBLE PRECISION)) AS cov_pct
  FROM h
  GROUP BY equipment_id
)
SELECT
  f.equipment_id,
  CASE
    WHEN 1 < 0.5 THEN SUM(f.confirmed) * 300 / 3600.0
    WHEN MAX(c.cov_pct) < 5 THEN 0.0
    ELSE SUM(f.confirmed) * 300 / 3600.0
  END AS fault_hours
FROM final f
LEFT JOIN cov c ON f.equipment_id = c.equipment_id
GROUP BY f.equipment_id;

EXECUTE fdd_rule_10;
DEALLOCATE fdd_rule_10;

-- FC3
PREPARE fdd_rule_11 AS
-- PostgreSQL adaptation. Render numeric template parameters with render_rule.py.
-- Inputs must be scoped to one tenant/site and cadence; see README.md.
-- fc3_mat_high.sql — FC3 mixed air above envelope + confirm (600s default)
WITH h AS (
  SELECT
    equipment_id,
    timestamp_utc,
    mat,
    oa_t,
    rat,
    COALESCE(CASE WHEN fan_cmd IS NULL THEN 0.0 WHEN fan_cmd > 1.0 THEN fan_cmd / 100.0 ELSE fan_cmd END, 0.0) AS fan,
        CASE
      WHEN 1 < 0.5 THEN 1
      WHEN fan_status IS NOT NULL THEN CASE WHEN fan_status > 0.05 THEN 1 ELSE 0 END
      WHEN fan_cmd IS NOT NULL THEN CASE WHEN (CASE WHEN fan_cmd > 1.0 THEN fan_cmd / 100.0 ELSE fan_cmd END) > 0.01 THEN 1 ELSE 0 END
      ELSE 1
    END AS fan_on

  FROM history
),
base AS (
  SELECT
    equipment_id,
    timestamp_utc,
    CAST(CASE
      WHEN COALESCE(fan_on, 1) = 0 THEN 0
      WHEN COALESCE(mode_stable, 1) = 0 THEN 0
      WHEN mat IS NOT NULL AND oa_t IS NOT NULL AND rat IS NOT NULL
       AND (mat - 1.15) > (CASE WHEN rat > oa_t THEN rat + 1.15 ELSE oa_t + 1.15 END)
      THEN 1 ELSE 0 END AS INT) AS raw_fault
  FROM (
  SELECT h.*,
    CASE
      WHEN COALESCE(fan_on, 1) = 0 THEN 0
      WHEN SUM(CASE WHEN COALESCE(fan_on, 1) = 0 THEN 1 ELSE 0 END) OVER (
        PARTITION BY equipment_id ORDER BY timestamp_utc
        ROWS BETWEEN 1 PRECEDING AND CURRENT ROW
      ) = 0 THEN 1
      ELSE 0
    END AS mode_stable
  FROM h
) h
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
    CASE WHEN raw_fault = 1 AND streak_len >= 2 THEN 1 ELSE 0 END AS confirmed
  FROM ranked
)
, cov AS (
  SELECT equipment_id,
    100.0 * AVG(CAST(COALESCE(fan_on, 1) AS DOUBLE PRECISION)) AS cov_pct
  FROM h
  GROUP BY equipment_id
)
SELECT
  f.equipment_id,
  CASE
    WHEN 1 < 0.5 THEN SUM(f.confirmed) * 300 / 3600.0
    WHEN MAX(c.cov_pct) < 5 THEN 0.0
    ELSE SUM(f.confirmed) * 300 / 3600.0
  END AS fault_hours
FROM final f
LEFT JOIN cov c ON f.equipment_id = c.equipment_id
GROUP BY f.equipment_id;

EXECUTE fdd_rule_11;
DEALLOCATE fdd_rule_11;

-- FC7
PREPARE fdd_rule_12 AS
-- PostgreSQL adaptation. Render numeric template parameters with render_rule.py.
-- Inputs must be scoped to one tenant/site and cadence; see README.md.
-- fc7_sat_low_heating.sql — FC7 SAT low while heating at full + confirm
WITH h AS (
  SELECT
    equipment_id,
    timestamp_utc,
    sat,
    sat_sp,
    COALESCE(
      CASE
        WHEN fan_status IS NOT NULL THEN CASE WHEN fan_status > 0.05 THEN 1.0 ELSE 0.0 END
        WHEN fan_cmd IS NULL THEN 0.0
        WHEN fan_cmd > 1.0 THEN fan_cmd / 100.0
        ELSE fan_cmd
      END,
      0.0
    ) AS fan,
    CASE
      WHEN 1 < 0.5 THEN 1
      WHEN fan_status IS NOT NULL THEN CASE WHEN fan_status > 0.05 THEN 1 ELSE 0 END
      WHEN fan_cmd IS NOT NULL THEN CASE WHEN (CASE WHEN fan_cmd > 1.0 THEN fan_cmd / 100.0 ELSE fan_cmd END) > 0.01 THEN 1 ELSE 0 END
      ELSE 1
    END AS fan_on,
    COALESCE(CASE WHEN htg_valve_pct IS NULL THEN NULL WHEN htg_valve_pct > 1.0 THEN htg_valve_pct / 100.0 ELSE htg_valve_pct END, 0.0) AS htg_valve_pct
  FROM history
),
base AS (
  SELECT
    equipment_id,
    timestamp_utc,
    CAST(CASE
      WHEN sat IS NOT NULL AND sat_sp IS NOT NULL AND fan > 0.01
       AND sat < sat_sp - 1.15 AND htg_valve_pct >= 0.9
      THEN 1 ELSE 0 END AS INT) AS raw_fault
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
    CASE WHEN raw_fault = 1 AND streak_len >= 2 THEN 1 ELSE 0 END AS confirmed
  FROM ranked
)
, cov AS (
  SELECT equipment_id,
    100.0 * AVG(CAST(COALESCE(fan_on, 1) AS DOUBLE PRECISION)) AS cov_pct
  FROM h
  GROUP BY equipment_id
)
SELECT
  f.equipment_id,
  CASE
    WHEN 1 < 0.5 THEN SUM(f.confirmed) * 300 / 3600.0
    WHEN MAX(c.cov_pct) < 5 THEN 0.0
    ELSE SUM(f.confirmed) * 300 / 3600.0
  END AS fault_hours
FROM final f
LEFT JOIN cov c ON f.equipment_id = c.equipment_id
GROUP BY f.equipment_id;

EXECUTE fdd_rule_12;
DEALLOCATE fdd_rule_12;

-- FC8
PREPARE fdd_rule_13 AS
-- PostgreSQL adaptation. Render numeric template parameters with render_rule.py.
-- Inputs must be scoped to one tenant/site and cadence; see README.md.
-- fc8_sat_mat_econ.sql — FC8 SAT vs MAT while economizing + confirm
WITH h AS (
  SELECT
    equipment_id,
    timestamp_utc,
    sat,
    mat,
    COALESCE(CASE WHEN oa_damper_pct IS NULL THEN NULL WHEN oa_damper_pct > 1.0 THEN oa_damper_pct / 100.0 ELSE oa_damper_pct END, 0.0) AS oa_damper_pct,
    COALESCE(CASE WHEN clg_valve_pct IS NULL THEN NULL WHEN clg_valve_pct > 1.0 THEN clg_valve_pct / 100.0 ELSE clg_valve_pct END, 0.0) AS clg_valve_pct,
    fan_cmd,
    fan_status,
        CASE
      WHEN 1 < 0.5 THEN 1
      WHEN fan_status IS NOT NULL THEN CASE WHEN fan_status > 0.05 THEN 1 ELSE 0 END
      WHEN fan_cmd IS NOT NULL THEN CASE WHEN (CASE WHEN fan_cmd > 1.0 THEN fan_cmd / 100.0 ELSE fan_cmd END) > 0.01 THEN 1 ELSE 0 END
      ELSE 1
    END AS fan_on

  FROM history
),
base AS (
  SELECT
    equipment_id,
    timestamp_utc,
    CAST(CASE
      WHEN COALESCE(fan_on, 1) = 0 THEN 0
      WHEN COALESCE(mode_stable, 1) = 0 THEN 0
      WHEN sat IS NOT NULL AND mat IS NOT NULL
       AND oa_damper_pct > 0.05 AND clg_valve_pct < 0.1
       AND ABS(sat - 0.55 - mat) > SQRT(1.15 * 1.15 + 1.15 * 1.15)
      THEN 1 ELSE 0 END AS INT) AS raw_fault
  FROM (
  SELECT h.*,
    CASE
      WHEN COALESCE(fan_on, 1) = 0 THEN 0
      WHEN SUM(CASE WHEN COALESCE(fan_on, 1) = 0 THEN 1 ELSE 0 END) OVER (
        PARTITION BY equipment_id ORDER BY timestamp_utc
        ROWS BETWEEN 1 PRECEDING AND CURRENT ROW
      ) = 0 THEN 1
      ELSE 0
    END AS mode_stable
  FROM h
) h
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
    CASE WHEN raw_fault = 1 AND streak_len >= 2 THEN 1 ELSE 0 END AS confirmed
  FROM ranked
)
, cov AS (
  SELECT equipment_id,
    100.0 * AVG(CAST(COALESCE(fan_on, 1) AS DOUBLE PRECISION)) AS cov_pct
  FROM h
  GROUP BY equipment_id
)
SELECT
  f.equipment_id,
  CASE
    WHEN 1 < 0.5 THEN SUM(f.confirmed) * 300 / 3600.0
    WHEN MAX(c.cov_pct) < 5 THEN 0.0
    ELSE SUM(f.confirmed) * 300 / 3600.0
  END AS fault_hours
FROM final f
LEFT JOIN cov c ON f.equipment_id = c.equipment_id
GROUP BY f.equipment_id;

EXECUTE fdd_rule_13;
DEALLOCATE fdd_rule_13;

-- FC9
PREPARE fdd_rule_14 AS
-- PostgreSQL adaptation. Render numeric template parameters with render_rule.py.
-- Inputs must be scoped to one tenant/site and cadence; see README.md.
-- fc9_oa_sat_sp_econ.sql — FC9 OAT high vs SAT SP while economizing + confirm
WITH h AS (
  SELECT
    equipment_id,
    timestamp_utc,
    oa_t,
    sat_sp,
    COALESCE(CASE WHEN oa_damper_pct IS NULL THEN NULL WHEN oa_damper_pct > 1.0 THEN oa_damper_pct / 100.0 ELSE oa_damper_pct END, 0.0) AS oa_damper_pct,
    COALESCE(CASE WHEN clg_valve_pct IS NULL THEN NULL WHEN clg_valve_pct > 1.0 THEN clg_valve_pct / 100.0 ELSE clg_valve_pct END, 0.0) AS clg_valve_pct,
    fan_cmd,
    fan_status,
        CASE
      WHEN 1 < 0.5 THEN 1
      WHEN fan_status IS NOT NULL THEN CASE WHEN fan_status > 0.05 THEN 1 ELSE 0 END
      WHEN fan_cmd IS NOT NULL THEN CASE WHEN (CASE WHEN fan_cmd > 1.0 THEN fan_cmd / 100.0 ELSE fan_cmd END) > 0.01 THEN 1 ELSE 0 END
      ELSE 1
    END AS fan_on

  FROM history
),
base AS (
  SELECT
    equipment_id,
    timestamp_utc,
    CAST(CASE
      WHEN COALESCE(fan_on, 1) = 0 THEN 0
      WHEN COALESCE(mode_stable, 1) = 0 THEN 0
      WHEN oa_t IS NOT NULL AND sat_sp IS NOT NULL
       AND oa_damper_pct > 0.05 AND clg_valve_pct < 0.1
       AND (oa_t - 1.15) > (sat_sp - 0.55 + 1.15)
      THEN 1 ELSE 0 END AS INT) AS raw_fault
  FROM (
  SELECT h.*,
    CASE
      WHEN COALESCE(fan_on, 1) = 0 THEN 0
      WHEN SUM(CASE WHEN COALESCE(fan_on, 1) = 0 THEN 1 ELSE 0 END) OVER (
        PARTITION BY equipment_id ORDER BY timestamp_utc
        ROWS BETWEEN 1 PRECEDING AND CURRENT ROW
      ) = 0 THEN 1
      ELSE 0
    END AS mode_stable
  FROM h
) h
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
    CASE WHEN raw_fault = 1 AND streak_len >= 2 THEN 1 ELSE 0 END AS confirmed
  FROM ranked
)
, cov AS (
  SELECT equipment_id,
    100.0 * AVG(CAST(COALESCE(fan_on, 1) AS DOUBLE PRECISION)) AS cov_pct
  FROM h
  GROUP BY equipment_id
)
SELECT
  f.equipment_id,
  CASE
    WHEN 1 < 0.5 THEN SUM(f.confirmed) * 300 / 3600.0
    WHEN MAX(c.cov_pct) < 5 THEN 0.0
    ELSE SUM(f.confirmed) * 300 / 3600.0
  END AS fault_hours
FROM final f
LEFT JOIN cov c ON f.equipment_id = c.equipment_id
GROUP BY f.equipment_id;

EXECUTE fdd_rule_14;
DEALLOCATE fdd_rule_14;

-- FC10
PREPARE fdd_rule_15 AS
-- PostgreSQL adaptation. Render numeric template parameters with render_rule.py.
-- Inputs must be scoped to one tenant/site and cadence; see README.md.
-- fc10_mat_oa_clg.sql — FC10 MAT-OAT delta while cooling + economizing + confirm
WITH h AS (
  SELECT
    equipment_id,
    timestamp_utc,
    mat,
    oa_t,
    COALESCE(CASE WHEN oa_damper_pct IS NULL THEN NULL WHEN oa_damper_pct > 1.0 THEN oa_damper_pct / 100.0 ELSE oa_damper_pct END, 0.0) AS oa_damper_pct,
    COALESCE(CASE WHEN clg_valve_pct IS NULL THEN NULL WHEN clg_valve_pct > 1.0 THEN clg_valve_pct / 100.0 ELSE clg_valve_pct END, 0.0) AS clg_valve_pct,
    fan_cmd,
    fan_status,
        CASE
      WHEN 1 < 0.5 THEN 1
      WHEN fan_status IS NOT NULL THEN CASE WHEN fan_status > 0.05 THEN 1 ELSE 0 END
      WHEN fan_cmd IS NOT NULL THEN CASE WHEN (CASE WHEN fan_cmd > 1.0 THEN fan_cmd / 100.0 ELSE fan_cmd END) > 0.01 THEN 1 ELSE 0 END
      ELSE 1
    END AS fan_on

  FROM history
),
base AS (
  SELECT
    equipment_id,
    timestamp_utc,
    CAST(CASE
      WHEN COALESCE(fan_on, 1) = 0 THEN 0
      WHEN COALESCE(mode_stable, 1) = 0 THEN 0
      WHEN mat IS NOT NULL AND oa_t IS NOT NULL
       AND clg_valve_pct > 0.01 AND oa_damper_pct > 0.9
       AND ABS(mat - oa_t) > SQRT(2.0 * 1.15 * 1.15)
      THEN 1 ELSE 0 END AS INT) AS raw_fault
  FROM (
  SELECT h.*,
    CASE
      WHEN COALESCE(fan_on, 1) = 0 THEN 0
      WHEN SUM(CASE WHEN COALESCE(fan_on, 1) = 0 THEN 1 ELSE 0 END) OVER (
        PARTITION BY equipment_id ORDER BY timestamp_utc
        ROWS BETWEEN 1 PRECEDING AND CURRENT ROW
      ) = 0 THEN 1
      ELSE 0
    END AS mode_stable
  FROM h
) h
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
    CASE WHEN raw_fault = 1 AND streak_len >= 2 THEN 1 ELSE 0 END AS confirmed
  FROM ranked
)
, cov AS (
  SELECT equipment_id,
    100.0 * AVG(CAST(COALESCE(fan_on, 1) AS DOUBLE PRECISION)) AS cov_pct
  FROM h
  GROUP BY equipment_id
)
SELECT
  f.equipment_id,
  CASE
    WHEN 1 < 0.5 THEN SUM(f.confirmed) * 300 / 3600.0
    WHEN MAX(c.cov_pct) < 5 THEN 0.0
    ELSE SUM(f.confirmed) * 300 / 3600.0
  END AS fault_hours
FROM final f
LEFT JOIN cov c ON f.equipment_id = c.equipment_id
GROUP BY f.equipment_id;

EXECUTE fdd_rule_15;
DEALLOCATE fdd_rule_15;

-- FC11
PREPARE fdd_rule_16 AS
-- PostgreSQL adaptation. Render numeric template parameters with render_rule.py.
-- Inputs must be scoped to one tenant/site and cadence; see README.md.
-- fc11_oa_sat_sp_clg.sql — FC11 OAT low vs SAT SP while cooling + economizing + confirm
WITH h AS (
  SELECT
    equipment_id,
    timestamp_utc,
    oa_t,
    sat_sp,
    COALESCE(CASE WHEN oa_damper_pct IS NULL THEN NULL WHEN oa_damper_pct > 1.0 THEN oa_damper_pct / 100.0 ELSE oa_damper_pct END, 0.0) AS oa_damper_pct,
    COALESCE(CASE WHEN clg_valve_pct IS NULL THEN NULL WHEN clg_valve_pct > 1.0 THEN clg_valve_pct / 100.0 ELSE clg_valve_pct END, 0.0) AS clg_valve_pct,
    fan_cmd,
    fan_status,
        CASE
      WHEN 1 < 0.5 THEN 1
      WHEN fan_status IS NOT NULL THEN CASE WHEN fan_status > 0.05 THEN 1 ELSE 0 END
      WHEN fan_cmd IS NOT NULL THEN CASE WHEN (CASE WHEN fan_cmd > 1.0 THEN fan_cmd / 100.0 ELSE fan_cmd END) > 0.01 THEN 1 ELSE 0 END
      ELSE 1
    END AS fan_on

  FROM history
),
base AS (
  SELECT
    equipment_id,
    timestamp_utc,
    CAST(CASE
      WHEN COALESCE(fan_on, 1) = 0 THEN 0
      WHEN COALESCE(mode_stable, 1) = 0 THEN 0
      WHEN oa_t IS NOT NULL AND sat_sp IS NOT NULL
       AND clg_valve_pct > 0.01 AND oa_damper_pct > 0.9
       AND (oa_t + 1.15) < (sat_sp - 0.55 - 1.15)
      THEN 1 ELSE 0 END AS INT) AS raw_fault
  FROM (
  SELECT h.*,
    CASE
      WHEN COALESCE(fan_on, 1) = 0 THEN 0
      WHEN SUM(CASE WHEN COALESCE(fan_on, 1) = 0 THEN 1 ELSE 0 END) OVER (
        PARTITION BY equipment_id ORDER BY timestamp_utc
        ROWS BETWEEN 1 PRECEDING AND CURRENT ROW
      ) = 0 THEN 1
      ELSE 0
    END AS mode_stable
  FROM h
) h
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
    CASE WHEN raw_fault = 1 AND streak_len >= 2 THEN 1 ELSE 0 END AS confirmed
  FROM ranked
)
, cov AS (
  SELECT equipment_id,
    100.0 * AVG(CAST(COALESCE(fan_on, 1) AS DOUBLE PRECISION)) AS cov_pct
  FROM h
  GROUP BY equipment_id
)
SELECT
  f.equipment_id,
  CASE
    WHEN 1 < 0.5 THEN SUM(f.confirmed) * 300 / 3600.0
    WHEN MAX(c.cov_pct) < 5 THEN 0.0
    ELSE SUM(f.confirmed) * 300 / 3600.0
  END AS fault_hours
FROM final f
LEFT JOIN cov c ON f.equipment_id = c.equipment_id
GROUP BY f.equipment_id;

EXECUTE fdd_rule_16;
DEALLOCATE fdd_rule_16;

-- FC12
PREPARE fdd_rule_17 AS
-- PostgreSQL adaptation. Render numeric template parameters with render_rule.py.
-- Inputs must be scoped to one tenant/site and cadence; see README.md.
-- fc12_sat_mat_clg.sql — FC12 SAT above MAT while cooling + confirm
WITH h AS (
  SELECT
    equipment_id,
    timestamp_utc,
    sat,
    mat,
    COALESCE(CASE WHEN oa_damper_pct IS NULL THEN NULL WHEN oa_damper_pct > 1.0 THEN oa_damper_pct / 100.0 ELSE oa_damper_pct END, 0.0) AS oa_damper_pct,
    COALESCE(CASE WHEN clg_valve_pct IS NULL THEN NULL WHEN clg_valve_pct > 1.0 THEN clg_valve_pct / 100.0 ELSE clg_valve_pct END, 0.0) AS clg_valve_pct,
    fan_cmd,
    fan_status,
        CASE
      WHEN 1 < 0.5 THEN 1
      WHEN fan_status IS NOT NULL THEN CASE WHEN fan_status > 0.05 THEN 1 ELSE 0 END
      WHEN fan_cmd IS NOT NULL THEN CASE WHEN (CASE WHEN fan_cmd > 1.0 THEN fan_cmd / 100.0 ELSE fan_cmd END) > 0.01 THEN 1 ELSE 0 END
      ELSE 1
    END AS fan_on

  FROM history
),
base AS (
  SELECT
    equipment_id,
    timestamp_utc,
    CAST(CASE
      WHEN COALESCE(fan_on, 1) = 0 THEN 0
      WHEN COALESCE(mode_stable, 1) = 0 THEN 0
      WHEN sat IS NOT NULL AND mat IS NOT NULL AND clg_valve_pct > 0.01
       AND (sat - 1.15 - 0.55) > (mat + 1.15)
       AND (oa_damper_pct <= 0.05 OR oa_damper_pct > 0.9)
      THEN 1 ELSE 0 END AS INT) AS raw_fault
  FROM (
  SELECT h.*,
    CASE
      WHEN COALESCE(fan_on, 1) = 0 THEN 0
      WHEN SUM(CASE WHEN COALESCE(fan_on, 1) = 0 THEN 1 ELSE 0 END) OVER (
        PARTITION BY equipment_id ORDER BY timestamp_utc
        ROWS BETWEEN 1 PRECEDING AND CURRENT ROW
      ) = 0 THEN 1
      ELSE 0
    END AS mode_stable
  FROM h
) h
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
    CASE WHEN raw_fault = 1 AND streak_len >= 2 THEN 1 ELSE 0 END AS confirmed
  FROM ranked
)
, cov AS (
  SELECT equipment_id,
    100.0 * AVG(CAST(COALESCE(fan_on, 1) AS DOUBLE PRECISION)) AS cov_pct
  FROM h
  GROUP BY equipment_id
)
SELECT
  f.equipment_id,
  CASE
    WHEN 1 < 0.5 THEN SUM(f.confirmed) * 300 / 3600.0
    WHEN MAX(c.cov_pct) < 5 THEN 0.0
    ELSE SUM(f.confirmed) * 300 / 3600.0
  END AS fault_hours
FROM final f
LEFT JOIN cov c ON f.equipment_id = c.equipment_id
GROUP BY f.equipment_id;

EXECUTE fdd_rule_17;
DEALLOCATE fdd_rule_17;

-- ECON-1
PREPARE fdd_rule_18 AS
-- PostgreSQL adaptation. Render numeric template parameters with render_rule.py.
-- Inputs must be scoped to one tenant/site and cadence; see README.md.
-- econ1_stuck_closed.sql — ECON-1 economizer stuck closed
-- CAST DOUBLE + percent gate >= 1.5 on damper and fan_cmd (B100 0–100).
-- Pandas _fan is fan-cmd first (percent-normalized), then fan-status (> 0.5).
WITH base AS (
  SELECT
    equipment_id,
    timestamp_utc,
    CAST(CASE
      WHEN CASE
        WHEN fan_cmd IS NOT NULL THEN CASE
          WHEN (
            CASE
              WHEN CAST(fan_cmd AS DOUBLE PRECISION) >= 1.5
              THEN CAST(fan_cmd AS DOUBLE PRECISION) / 100.0
              ELSE CAST(fan_cmd AS DOUBLE PRECISION)
            END
          ) > 0.01 THEN 1
          ELSE 0
        END
        WHEN fan_status IS NOT NULL THEN CASE WHEN CAST(fan_status AS DOUBLE PRECISION) > 0.5 THEN 1 ELSE 0 END
        ELSE 0
      END = 0 THEN 0
      WHEN oa_damper_pct IS NOT NULL AND oa_t IS NOT NULL
       AND (
         CASE
           WHEN CAST(oa_damper_pct AS DOUBLE PRECISION) >= 1.5
           THEN CAST(oa_damper_pct AS DOUBLE PRECISION) / 100.0
           ELSE CAST(oa_damper_pct AS DOUBLE PRECISION)
         END
       ) < 0.05
       AND CAST(oa_t AS DOUBLE PRECISION) > 55
      THEN 1 ELSE 0 END AS INT) AS raw_fault
  FROM history
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
    CASE WHEN raw_fault = 1 AND streak_len >= 2 THEN 1 ELSE 0 END AS confirmed
  FROM ranked
)
SELECT
  equipment_id,
  SUM(confirmed) * 300 / 3600.0 AS fault_hours
FROM final
GROUP BY equipment_id;

EXECUTE fdd_rule_18;
DEALLOCATE fdd_rule_18;

-- ECON-4
PREPARE fdd_rule_19 AS
-- PostgreSQL adaptation. Render numeric template parameters with render_rule.py.
-- Inputs must be scoped to one tenant/site and cadence; see README.md.
-- econ4_low_oa_frac.sql — ECON-4 low estimated OA fraction + confirm (600s)
WITH h AS (
  SELECT
    equipment_id,
    timestamp_utc,
    mat,
    rat,
    oa_t,
    COALESCE(CASE WHEN fan_cmd IS NULL THEN 0.0 WHEN fan_cmd > 1.0 THEN fan_cmd / 100.0 ELSE fan_cmd END, 0.0) AS fan,
    CASE
      WHEN fan_status IS NOT NULL THEN CASE WHEN fan_status > 0.05 THEN 1 ELSE 0 END
      WHEN fan_cmd IS NOT NULL THEN CASE WHEN (CASE WHEN fan_cmd > 1.0 THEN fan_cmd / 100.0 ELSE fan_cmd END) > 0.01 THEN 1 ELSE 0 END
      ELSE 1
    END AS fan_on

  FROM history
),
base AS (
  SELECT
    equipment_id,
    timestamp_utc,
    CAST(CASE
      WHEN COALESCE(fan_on, 1) = 0 THEN 0
      WHEN fan > 0.01 AND mat IS NOT NULL AND rat IS NOT NULL AND oa_t IS NOT NULL
       AND ABS(rat - oa_t) > 2.2
       AND ((mat - rat) / NULLIF(oa_t - rat, 0)) * 100.0 < 21
      THEN 1 ELSE 0 END AS INT) AS raw_fault
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
    CASE WHEN raw_fault = 1 AND streak_len >= 2 THEN 1 ELSE 0 END AS confirmed
  FROM ranked
)
SELECT
  equipment_id,
  SUM(confirmed) * 300 / 3600.0 AS fault_hours
FROM final
GROUP BY equipment_id;

EXECUTE fdd_rule_19;
DEALLOCATE fdd_rule_19;

-- SV-RANGE
PREPARE fdd_rule_20 AS
-- PostgreSQL adaptation. Render numeric template parameters with render_rule.py.
-- Inputs must be scoped to one tenant/site and cadence; see README.md.
-- sv_range.sql — Sensor out of hard range (pandas SENSOR_LIMITS catalog)
-- Do not force everything through oa_t. Humidity/pressure are not temperature-scaled.
WITH h AS (
  SELECT
    equipment_id,
    timestamp_utc,
    oa_t, mat, zone_t, rat, sat,
    chw_supply_t, chw_return_t, hw_supply_t, hw_return_t, oa_h, duct_static,
    fan_cmd, fan_status, pump_status, chw_pump_cmd, chiller_status,
    CASE
      WHEN fan_status IS NOT NULL THEN CASE WHEN fan_status > 0.05 THEN 1 ELSE 0 END
      WHEN fan_cmd IS NOT NULL THEN CASE WHEN (CASE WHEN fan_cmd > 1.0 THEN fan_cmd / 100.0 ELSE fan_cmd END) > 0.01 THEN 1 ELSE 0 END
      WHEN pump_status IS NOT NULL THEN CASE WHEN pump_status > 0.05 THEN 1 ELSE 0 END
      WHEN chw_pump_cmd IS NOT NULL THEN CASE WHEN (CASE WHEN chw_pump_cmd > 1.0 THEN chw_pump_cmd / 100.0 ELSE chw_pump_cmd END) > 0.05 THEN 1 ELSE 0 END
      WHEN chiller_status IS NOT NULL THEN CASE WHEN chiller_status > 0.05 THEN 1 ELSE 0 END
      ELSE 1
    END AS energized
  FROM history
),
base AS (
  SELECT
    equipment_id,
    timestamp_utc,
    CAST(CASE
      WHEN COALESCE(energized, 0) = 0 THEN 0
      WHEN oa_t IS NOT NULL AND (oa_t = CAST('NaN' AS DOUBLE PRECISION) OR oa_t < -60.0 * 1 OR oa_t > 130.0 * 1) THEN 1
      WHEN mat IS NOT NULL AND (mat = CAST('NaN' AS DOUBLE PRECISION) OR mat < -20.0 * 1 OR mat > 110.0 * 1) THEN 1
      WHEN zone_t IS NOT NULL AND (zone_t = CAST('NaN' AS DOUBLE PRECISION) OR zone_t < 40.0 * 1 OR zone_t > 100.0 * 1) THEN 1
      WHEN rat IS NOT NULL AND (rat = CAST('NaN' AS DOUBLE PRECISION) OR rat < 40.0 * 1 OR rat > 100.0 * 1) THEN 1
      WHEN sat IS NOT NULL AND (sat = CAST('NaN' AS DOUBLE PRECISION) OR sat < 30.0 * 1 OR sat > 150.0 * 1) THEN 1
      WHEN chw_supply_t IS NOT NULL AND (chw_supply_t = CAST('NaN' AS DOUBLE PRECISION) OR chw_supply_t < 30.0 * 1 OR chw_supply_t > 80.0 * 1) THEN 1
      WHEN chw_return_t IS NOT NULL AND (chw_return_t = CAST('NaN' AS DOUBLE PRECISION) OR chw_return_t < 30.0 * 1 OR chw_return_t > 90.0 * 1) THEN 1
      WHEN hw_supply_t IS NOT NULL AND (hw_supply_t = CAST('NaN' AS DOUBLE PRECISION) OR hw_supply_t < 40.0 * 1 OR hw_supply_t > 220.0 * 1) THEN 1
      WHEN hw_return_t IS NOT NULL AND (hw_return_t = CAST('NaN' AS DOUBLE PRECISION) OR hw_return_t < 40.0 * 1 OR hw_return_t > 220.0 * 1) THEN 1
      WHEN oa_h IS NOT NULL AND (oa_h = CAST('NaN' AS DOUBLE PRECISION) OR oa_h < 0.0 * 1 OR oa_h > 100.0 * 1) THEN 1
      WHEN duct_static IS NOT NULL AND (duct_static = CAST('NaN' AS DOUBLE PRECISION) OR duct_static < -1.0 * 1 OR duct_static > 8.0 * 1) THEN 1
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
    CASE WHEN raw_fault = 1 AND streak_len >= 1 THEN 1 ELSE 0 END AS confirmed
  FROM ranked
)
SELECT
  equipment_id,
  SUM(confirmed) * 300 / 3600.0 AS fault_hours
FROM final
GROUP BY equipment_id;

EXECUTE fdd_rule_20;
DEALLOCATE fdd_rule_20;

-- SV-FLATLINE
PREPARE fdd_rule_21 AS
-- PostgreSQL adaptation. Render numeric template parameters with render_rule.py.
-- Inputs must be scoped to one tenant/site and cadence; see README.md.
-- sv_flatline.sql — Sensor flatline (stuck) — pandas FLATLINE_SENSOR_ROLES catalog
-- Temperature/humidity analogs (SENSOR_LIMITS minus duct static). Faults when ANY
-- mapped role is flat while the equipment is energized.
-- 12 / 11 are derived from FLATLINE_HOURS
-- and POLL_SECONDS (DataFusion requires literal ROWS frame bounds).
WITH h AS (
  SELECT
    equipment_id,
    timestamp_utc,
    oa_t, mat, zone_t, rat, sat,
    chw_supply_t, chw_return_t, hw_supply_t, hw_return_t, oa_h,
    CASE
      WHEN fan_status IS NOT NULL THEN CASE WHEN fan_status > 0.05 THEN 1 ELSE 0 END
      WHEN fan_cmd IS NOT NULL THEN CASE WHEN (CASE WHEN fan_cmd > 1.0 THEN fan_cmd / 100.0 ELSE fan_cmd END) > 0.01 THEN 1 ELSE 0 END
      WHEN pump_status IS NOT NULL THEN CASE WHEN pump_status > 0.05 THEN 1 ELSE 0 END
      WHEN chw_pump_cmd IS NOT NULL THEN CASE WHEN (CASE WHEN chw_pump_cmd > 1.0 THEN chw_pump_cmd / 100.0 ELSE chw_pump_cmd END) > 0.05 THEN 1 ELSE 0 END
      WHEN chiller_status IS NOT NULL THEN CASE WHEN chiller_status > 0.05 THEN 1 ELSE 0 END
      ELSE 1
    END AS energized
  FROM history
),
win AS (
  SELECT
    equipment_id,
    timestamp_utc,
    energized,
    COUNT(oa_t) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS BETWEEN 11 PRECEDING AND CURRENT ROW) AS n_oa_t,
    MAX(oa_t) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS BETWEEN 11 PRECEDING AND CURRENT ROW)
      - MIN(oa_t) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS BETWEEN 11 PRECEDING AND CURRENT ROW) AS span_oa_t,
    COUNT(mat) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS BETWEEN 11 PRECEDING AND CURRENT ROW) AS n_mat,
    MAX(mat) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS BETWEEN 11 PRECEDING AND CURRENT ROW)
      - MIN(mat) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS BETWEEN 11 PRECEDING AND CURRENT ROW) AS span_mat,
    COUNT(zone_t) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS BETWEEN 11 PRECEDING AND CURRENT ROW) AS n_zone_t,
    MAX(zone_t) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS BETWEEN 11 PRECEDING AND CURRENT ROW)
      - MIN(zone_t) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS BETWEEN 11 PRECEDING AND CURRENT ROW) AS span_zone_t,
    COUNT(rat) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS BETWEEN 11 PRECEDING AND CURRENT ROW) AS n_rat,
    MAX(rat) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS BETWEEN 11 PRECEDING AND CURRENT ROW)
      - MIN(rat) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS BETWEEN 11 PRECEDING AND CURRENT ROW) AS span_rat,
    COUNT(sat) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS BETWEEN 11 PRECEDING AND CURRENT ROW) AS n_sat,
    MAX(sat) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS BETWEEN 11 PRECEDING AND CURRENT ROW)
      - MIN(sat) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS BETWEEN 11 PRECEDING AND CURRENT ROW) AS span_sat,
    COUNT(chw_supply_t) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS BETWEEN 11 PRECEDING AND CURRENT ROW) AS n_chw_supply_t,
    MAX(chw_supply_t) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS BETWEEN 11 PRECEDING AND CURRENT ROW)
      - MIN(chw_supply_t) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS BETWEEN 11 PRECEDING AND CURRENT ROW) AS span_chw_supply_t,
    COUNT(chw_return_t) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS BETWEEN 11 PRECEDING AND CURRENT ROW) AS n_chw_return_t,
    MAX(chw_return_t) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS BETWEEN 11 PRECEDING AND CURRENT ROW)
      - MIN(chw_return_t) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS BETWEEN 11 PRECEDING AND CURRENT ROW) AS span_chw_return_t,
    COUNT(hw_supply_t) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS BETWEEN 11 PRECEDING AND CURRENT ROW) AS n_hw_supply_t,
    MAX(hw_supply_t) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS BETWEEN 11 PRECEDING AND CURRENT ROW)
      - MIN(hw_supply_t) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS BETWEEN 11 PRECEDING AND CURRENT ROW) AS span_hw_supply_t,
    COUNT(hw_return_t) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS BETWEEN 11 PRECEDING AND CURRENT ROW) AS n_hw_return_t,
    MAX(hw_return_t) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS BETWEEN 11 PRECEDING AND CURRENT ROW)
      - MIN(hw_return_t) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS BETWEEN 11 PRECEDING AND CURRENT ROW) AS span_hw_return_t,
    COUNT(oa_h) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS BETWEEN 11 PRECEDING AND CURRENT ROW) AS n_oa_h,
    MAX(oa_h) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS BETWEEN 11 PRECEDING AND CURRENT ROW)
      - MIN(oa_h) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS BETWEEN 11 PRECEDING AND CURRENT ROW) AS span_oa_h
  FROM h
),
base AS (
  SELECT
    equipment_id,
    timestamp_utc,
    CAST(CASE
      WHEN COALESCE(energized, 0) = 0 THEN 0
      WHEN n_oa_t >= 12 AND span_oa_t <= 0.1 THEN 1
      WHEN n_mat >= 12 AND span_mat <= 0.1 THEN 1
      WHEN n_zone_t >= 12 AND span_zone_t <= 0.1 THEN 1
      WHEN n_rat >= 12 AND span_rat <= 0.1 THEN 1
      WHEN n_sat >= 12 AND span_sat <= 0.1 THEN 1
      WHEN n_chw_supply_t >= 12 AND span_chw_supply_t <= 0.1 THEN 1
      WHEN n_chw_return_t >= 12 AND span_chw_return_t <= 0.1 THEN 1
      WHEN n_hw_supply_t >= 12 AND span_hw_supply_t <= 0.1 THEN 1
      WHEN n_hw_return_t >= 12 AND span_hw_return_t <= 0.1 THEN 1
      WHEN n_oa_h >= 12 AND span_oa_h <= 0.1 THEN 1
      ELSE 0
    END AS INT) AS raw_fault
  FROM win
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
    CASE WHEN raw_fault = 1 AND streak_len >= 1 THEN 1 ELSE 0 END AS confirmed
  FROM ranked
)
SELECT
  equipment_id,
  SUM(confirmed) * 300 / 3600.0 AS fault_hours
FROM final
GROUP BY equipment_id;

EXECUTE fdd_rule_21;
DEALLOCATE fdd_rule_21;

-- SV-SPIKE
PREPARE fdd_rule_22 AS
-- PostgreSQL adaptation. Render numeric template parameters with render_rule.py.
-- Inputs must be scoped to one tenant/site and cadence; see README.md.
-- sv_spike.sql — Sensor rate-of-change spike — pandas SENSOR_LIMITS catalog
-- Per-role spike limits (scaled by SPIKE_SCALE). Humidity/pressure included.
WITH h AS (
  SELECT
    equipment_id,
    timestamp_utc,
    oa_t, mat, zone_t, rat, sat,
    chw_supply_t, chw_return_t, hw_supply_t, hw_return_t, oa_h, duct_static,
    LAG(oa_t) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc) AS prev_oa_t,
    LAG(mat) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc) AS prev_mat,
    LAG(zone_t) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc) AS prev_zone_t,
    LAG(rat) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc) AS prev_rat,
    LAG(sat) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc) AS prev_sat,
    LAG(chw_supply_t) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc) AS prev_chw_supply_t,
    LAG(chw_return_t) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc) AS prev_chw_return_t,
    LAG(hw_supply_t) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc) AS prev_hw_supply_t,
    LAG(hw_return_t) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc) AS prev_hw_return_t,
    LAG(oa_h) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc) AS prev_oa_h,
    LAG(duct_static) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc) AS prev_duct_static,
    fan_cmd, fan_status, pump_status, chw_pump_cmd, chiller_status,
    CASE
      WHEN fan_status IS NOT NULL THEN CASE WHEN fan_status > 0.05 THEN 1 ELSE 0 END
      WHEN fan_cmd IS NOT NULL THEN CASE WHEN (CASE WHEN fan_cmd > 1.0 THEN fan_cmd / 100.0 ELSE fan_cmd END) > 0.01 THEN 1 ELSE 0 END
      WHEN pump_status IS NOT NULL THEN CASE WHEN pump_status > 0.05 THEN 1 ELSE 0 END
      WHEN chw_pump_cmd IS NOT NULL THEN CASE WHEN (CASE WHEN chw_pump_cmd > 1.0 THEN chw_pump_cmd / 100.0 ELSE chw_pump_cmd END) > 0.05 THEN 1 ELSE 0 END
      WHEN chiller_status IS NOT NULL THEN CASE WHEN chiller_status > 0.05 THEN 1 ELSE 0 END
      ELSE 1
    END AS energized
  FROM history
),
base AS (
  SELECT
    equipment_id,
    timestamp_utc,
    CAST(CASE
      WHEN 1 >= 0.5 AND COALESCE(energized, 0) = 0 THEN 0
      WHEN oa_t IS NOT NULL AND prev_oa_t IS NOT NULL AND ABS(oa_t - prev_oa_t) > 36.0 * 1 THEN 1
      WHEN mat IS NOT NULL AND prev_mat IS NOT NULL AND ABS(mat - prev_mat) > 25.0 * 1 THEN 1
      WHEN zone_t IS NOT NULL AND prev_zone_t IS NOT NULL AND ABS(zone_t - prev_zone_t) > 12.0 * 1 THEN 1
      WHEN rat IS NOT NULL AND prev_rat IS NOT NULL AND ABS(rat - prev_rat) > 12.0 * 1 THEN 1
      WHEN sat IS NOT NULL AND prev_sat IS NOT NULL AND ABS(sat - prev_sat) > 40.0 * 1 THEN 1
      WHEN chw_supply_t IS NOT NULL AND prev_chw_supply_t IS NOT NULL AND ABS(chw_supply_t - prev_chw_supply_t) > 20.0 * 1 THEN 1
      WHEN chw_return_t IS NOT NULL AND prev_chw_return_t IS NOT NULL AND ABS(chw_return_t - prev_chw_return_t) > 20.0 * 1 THEN 1
      WHEN hw_supply_t IS NOT NULL AND prev_hw_supply_t IS NOT NULL AND ABS(hw_supply_t - prev_hw_supply_t) > 60.0 * 1 THEN 1
      WHEN hw_return_t IS NOT NULL AND prev_hw_return_t IS NOT NULL AND ABS(hw_return_t - prev_hw_return_t) > 60.0 * 1 THEN 1
      WHEN oa_h IS NOT NULL AND prev_oa_h IS NOT NULL AND ABS(oa_h - prev_oa_h) > 25.0 * 1 THEN 1
      WHEN duct_static IS NOT NULL AND prev_duct_static IS NOT NULL AND ABS(duct_static - prev_duct_static) > 2.0 * 1 THEN 1
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
    CASE WHEN raw_fault = 1 AND streak_len >= 1 THEN 1 ELSE 0 END AS confirmed
  FROM ranked
)
, cov AS (
  SELECT equipment_id,
    100.0 * AVG(CAST(COALESCE(energized, 1) AS DOUBLE PRECISION)) AS cov_pct
  FROM h
  GROUP BY equipment_id
)
SELECT
  f.equipment_id,
  CASE
    WHEN 1 < 0.5 THEN SUM(f.confirmed) * 300 / 3600.0
    WHEN MAX(c.cov_pct) < 5 THEN 0.0
    ELSE SUM(f.confirmed) * 300 / 3600.0
  END AS fault_hours
FROM final f
LEFT JOIN cov c ON f.equipment_id = c.equipment_id
GROUP BY f.equipment_id;

EXECUTE fdd_rule_22;
DEALLOCATE fdd_rule_22;

-- SV-STALE
PREPARE fdd_rule_23 AS
-- PostgreSQL adaptation. Render numeric template parameters with render_rule.py.
-- Inputs must be scoped to one tenant/site and cadence; see README.md.
-- sv_stale.sql — Stale data (no fresh samples)
-- Pandas gate is `always` — do not filter fan_cmd (off-period stale still counts).
-- Pandas `_sweep_stale` ANDs FLATLINE_SENSOR_ROLES (SENSOR_LIMITS minus duct static).
-- SQL windows that catalog: five air temps plus chw/hw temps and oa_h.
-- Every mapped analog must sit inside STALE_TOL across the trailing STALE_HOURS
-- window: one live sensor is enough to prove the feed is still updating.
-- 24 / 23 are derived from STALE_HOURS and
-- POLL_SECONDS (DataFusion requires literal ROWS frame bounds).
WITH win AS (
  SELECT
    equipment_id,
    timestamp_utc,
    COUNT(oa_t) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS BETWEEN 23 PRECEDING AND CURRENT ROW) AS n_oa_t,
    MAX(oa_t) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS BETWEEN 23 PRECEDING AND CURRENT ROW)
      - MIN(oa_t) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS BETWEEN 23 PRECEDING AND CURRENT ROW) AS span_oa_t,
    COUNT(mat) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS BETWEEN 23 PRECEDING AND CURRENT ROW) AS n_mat,
    MAX(mat) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS BETWEEN 23 PRECEDING AND CURRENT ROW)
      - MIN(mat) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS BETWEEN 23 PRECEDING AND CURRENT ROW) AS span_mat,
    COUNT(zone_t) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS BETWEEN 23 PRECEDING AND CURRENT ROW) AS n_zone_t,
    MAX(zone_t) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS BETWEEN 23 PRECEDING AND CURRENT ROW)
      - MIN(zone_t) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS BETWEEN 23 PRECEDING AND CURRENT ROW) AS span_zone_t,
    COUNT(rat) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS BETWEEN 23 PRECEDING AND CURRENT ROW) AS n_rat,
    MAX(rat) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS BETWEEN 23 PRECEDING AND CURRENT ROW)
      - MIN(rat) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS BETWEEN 23 PRECEDING AND CURRENT ROW) AS span_rat,
    COUNT(sat) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS BETWEEN 23 PRECEDING AND CURRENT ROW) AS n_sat,
    MAX(sat) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS BETWEEN 23 PRECEDING AND CURRENT ROW)
      - MIN(sat) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS BETWEEN 23 PRECEDING AND CURRENT ROW) AS span_sat,
    COUNT(chw_supply_t) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS BETWEEN 23 PRECEDING AND CURRENT ROW) AS n_chw_supply_t,
    MAX(chw_supply_t) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS BETWEEN 23 PRECEDING AND CURRENT ROW)
      - MIN(chw_supply_t) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS BETWEEN 23 PRECEDING AND CURRENT ROW) AS span_chw_supply_t,
    COUNT(chw_return_t) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS BETWEEN 23 PRECEDING AND CURRENT ROW) AS n_chw_return_t,
    MAX(chw_return_t) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS BETWEEN 23 PRECEDING AND CURRENT ROW)
      - MIN(chw_return_t) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS BETWEEN 23 PRECEDING AND CURRENT ROW) AS span_chw_return_t,
    COUNT(hw_supply_t) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS BETWEEN 23 PRECEDING AND CURRENT ROW) AS n_hw_supply_t,
    MAX(hw_supply_t) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS BETWEEN 23 PRECEDING AND CURRENT ROW)
      - MIN(hw_supply_t) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS BETWEEN 23 PRECEDING AND CURRENT ROW) AS span_hw_supply_t,
    COUNT(hw_return_t) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS BETWEEN 23 PRECEDING AND CURRENT ROW) AS n_hw_return_t,
    MAX(hw_return_t) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS BETWEEN 23 PRECEDING AND CURRENT ROW)
      - MIN(hw_return_t) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS BETWEEN 23 PRECEDING AND CURRENT ROW) AS span_hw_return_t,
    COUNT(oa_h) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS BETWEEN 23 PRECEDING AND CURRENT ROW) AS n_oa_h,
    MAX(oa_h) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS BETWEEN 23 PRECEDING AND CURRENT ROW)
      - MIN(oa_h) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS BETWEEN 23 PRECEDING AND CURRENT ROW) AS span_oa_h
  FROM history
),
scored AS (
  SELECT
    equipment_id,
    timestamp_utc,
    CASE WHEN n_oa_t >= 24 THEN 1 ELSE 0 END
      + CASE WHEN n_mat >= 24 THEN 1 ELSE 0 END
      + CASE WHEN n_zone_t >= 24 THEN 1 ELSE 0 END
      + CASE WHEN n_rat >= 24 THEN 1 ELSE 0 END
      + CASE WHEN n_sat >= 24 THEN 1 ELSE 0 END
      + CASE WHEN n_chw_supply_t >= 24 THEN 1 ELSE 0 END
      + CASE WHEN n_chw_return_t >= 24 THEN 1 ELSE 0 END
      + CASE WHEN n_hw_supply_t >= 24 THEN 1 ELSE 0 END
      + CASE WHEN n_hw_return_t >= 24 THEN 1 ELSE 0 END
      + CASE WHEN n_oa_h >= 24 THEN 1 ELSE 0 END AS roles_mapped,
    CASE WHEN n_oa_t >= 24 AND span_oa_t <= 0.05 THEN 1 ELSE 0 END
      + CASE WHEN n_mat >= 24 AND span_mat <= 0.05 THEN 1 ELSE 0 END
      + CASE WHEN n_zone_t >= 24 AND span_zone_t <= 0.05 THEN 1 ELSE 0 END
      + CASE WHEN n_rat >= 24 AND span_rat <= 0.05 THEN 1 ELSE 0 END
      + CASE WHEN n_sat >= 24 AND span_sat <= 0.05 THEN 1 ELSE 0 END
      + CASE WHEN n_chw_supply_t >= 24 AND span_chw_supply_t <= 0.05 THEN 1 ELSE 0 END
      + CASE WHEN n_chw_return_t >= 24 AND span_chw_return_t <= 0.05 THEN 1 ELSE 0 END
      + CASE WHEN n_hw_supply_t >= 24 AND span_hw_supply_t <= 0.05 THEN 1 ELSE 0 END
      + CASE WHEN n_hw_return_t >= 24 AND span_hw_return_t <= 0.05 THEN 1 ELSE 0 END
      + CASE WHEN n_oa_h >= 24 AND span_oa_h <= 0.05 THEN 1 ELSE 0 END AS roles_stale
  FROM win
),
base AS (
  SELECT
    equipment_id,
    timestamp_utc,
    CAST(CASE
      WHEN roles_mapped > 0 AND roles_stale = roles_mapped THEN 1
      ELSE 0
    END AS INT) AS raw_fault
  FROM scored
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
    CASE WHEN raw_fault = 1 AND streak_len >= 1 THEN 1 ELSE 0 END AS confirmed
  FROM ranked
)
SELECT
  equipment_id,
  SUM(confirmed) * 300 / 3600.0 AS fault_hours
FROM final
GROUP BY equipment_id;

EXECUTE fdd_rule_23;
DEALLOCATE fdd_rule_23;

-- SV-RATE
PREPARE fdd_rule_24 AS
-- PostgreSQL adaptation. Render numeric template parameters with render_rule.py.
-- Inputs must be scoped to one tenant/site and cadence; see README.md.
-- sv_rate.sql — Context-aware sensor rate of change (portable channels)
-- Rate is normalized to °F/h so the threshold is poll-interval independent, and
-- the exceedance must be *sustained* (two consecutive samples) to separate a
-- slew from a one-sample SV-SPIKE. Samples separated by more than
-- PERSISTENCE_MIN are treated as a data gap, not a slew.
WITH h AS (
  SELECT
    equipment_id,
    timestamp_utc,
    oa_t, mat, zone_t, rat, sat,
    LAG(oa_t) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc) AS prev_oa_t,
    LAG(mat) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc) AS prev_mat,
    LAG(zone_t) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc) AS prev_zone_t,
    LAG(rat) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc) AS prev_rat,
    LAG(sat) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc) AS prev_sat,
    LAG(timestamp_utc) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc) AS prev_ts
  FROM history
),
rates AS (
  SELECT
    equipment_id,
    timestamp_utc,
    CAST(EXTRACT(EPOCH FROM (timestamp_utc - prev_ts)) AS DOUBLE PRECISION) / 3600.0 AS dt_hours,
    oa_t - prev_oa_t AS d_oa_t,
    mat - prev_mat AS d_mat,
    zone_t - prev_zone_t AS d_zone_t,
    rat - prev_rat AS d_rat,
    sat - prev_sat AS d_sat,
    prev_ts
  FROM h
),
flagged AS (
  SELECT
    equipment_id,
    timestamp_utc,
    CAST(CASE
      WHEN prev_ts IS NULL THEN 0
      WHEN CAST(EXTRACT(EPOCH FROM (timestamp_utc - prev_ts)) AS DOUBLE PRECISION) > 1 * 3600.0 THEN 0
      WHEN dt_hours IS NULL OR dt_hours <= 0.0 THEN 0
      WHEN ABS(d_oa_t) / dt_hours > (6 * 100 / 100.0) THEN 1
      WHEN ABS(d_mat) / dt_hours > (6 * 100 / 100.0) THEN 1
      WHEN ABS(d_zone_t) / dt_hours > (6 * 100 / 100.0) THEN 1
      WHEN ABS(d_rat) / dt_hours > (6 * 100 / 100.0) THEN 1
      WHEN ABS(d_sat) / dt_hours > (6 * 100 / 100.0) THEN 1
      ELSE 0
    END AS INT) AS over_rate
  FROM rates
),
base AS (
  SELECT
    equipment_id,
    timestamp_utc,
    CAST(CASE
      WHEN over_rate = 1
       AND COALESCE(LAG(over_rate) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc), 0) = 1
      THEN 1 ELSE 0
    END AS INT) AS raw_fault
  FROM flagged
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
    CASE WHEN raw_fault = 1 AND streak_len >= 2 THEN 1 ELSE 0 END AS confirmed
  FROM ranked
)
SELECT
  equipment_id,
  SUM(confirmed) * 300 / 3600.0 AS fault_hours
FROM final
GROUP BY equipment_id;

EXECUTE fdd_rule_24;
DEALLOCATE fdd_rule_24;

-- PID-HUNT-1
PREPARE fdd_rule_25 AS
-- PostgreSQL adaptation. Render numeric template parameters with render_rule.py.
-- Inputs must be scoped to one tenant/site and cadence; see README.md.
-- pid_hunt_1.sql — Suspected control-output hunting (rolling 1h metrics)
-- Matches pandas hunting_fault_mask: TV / span / cycles / reversals over
-- WINDOW_HOURS. Sample-to-sample Δ alone under-counts the golden hangover
-- window (0.917h vs 1.0h). 12 / 11 are
-- derived from WINDOW_HOURS + POLL_SECONDS (DataFusion needs literal ROWS).
WITH h AS (
  SELECT
    equipment_id,
    timestamp_utc,
    CASE
      WHEN oa_damper_pct IS NOT NULL THEN
        CASE WHEN oa_damper_pct > 1.0 THEN oa_damper_pct ELSE oa_damper_pct * 100.0 END
      WHEN clg_valve_pct IS NOT NULL THEN
        CASE WHEN clg_valve_pct > 1.0 THEN clg_valve_pct ELSE clg_valve_pct * 100.0 END
      WHEN htg_valve_pct IS NOT NULL THEN
        CASE WHEN htg_valve_pct > 1.0 THEN htg_valve_pct ELSE htg_valve_pct * 100.0 END
      WHEN damper_pct IS NOT NULL THEN
        CASE WHEN damper_pct > 1.0 THEN damper_pct ELSE damper_pct * 100.0 END
      ELSE NULL
    END AS out_pct,
    LAG(
      CASE
        WHEN oa_damper_pct IS NOT NULL THEN
          CASE WHEN oa_damper_pct > 1.0 THEN oa_damper_pct ELSE oa_damper_pct * 100.0 END
        WHEN clg_valve_pct IS NOT NULL THEN
          CASE WHEN clg_valve_pct > 1.0 THEN clg_valve_pct ELSE clg_valve_pct * 100.0 END
        WHEN htg_valve_pct IS NOT NULL THEN
          CASE WHEN htg_valve_pct > 1.0 THEN htg_valve_pct ELSE htg_valve_pct * 100.0 END
        WHEN damper_pct IS NOT NULL THEN
          CASE WHEN damper_pct > 1.0 THEN damper_pct ELSE damper_pct * 100.0 END
        ELSE NULL
      END
    ) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc) AS prev_out,
    COALESCE(loop_enabled, 1.0) AS loop_on,
    CASE
      WHEN fan_status IS NOT NULL THEN CASE WHEN fan_status > 0.05 THEN 1 ELSE 0 END
      WHEN fan_cmd IS NOT NULL THEN CASE WHEN (CASE WHEN fan_cmd > 1.0 THEN fan_cmd / 100.0 ELSE fan_cmd END) > 0.01 THEN 1 ELSE 0 END
      ELSE 1
    END AS fan_on
  FROM history
),
deltas AS (
  SELECT
    *,
    CASE
      WHEN prev_out IS NULL OR out_pct IS NULL THEN NULL
      WHEN ABS(out_pct - prev_out) >= 1 THEN out_pct - prev_out
      ELSE 0.0
    END AS sig_delta
  FROM h
),
steps AS (
  SELECT
    *,
    CASE
      WHEN sig_delta IS NULL THEN 0
      ELSE ABS(sig_delta)
    END AS abs_step,
    CASE
      WHEN sig_delta IS NULL OR sig_delta = 0 THEN 0
      WHEN LAG(sig_delta) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc) IS NULL THEN 0
      WHEN LAG(sig_delta) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc) = 0 THEN 0
      WHEN sig_delta * LAG(sig_delta) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc) < 0 THEN 1
      ELSE 0
    END AS reversal_event
  FROM deltas
),
win AS (
  SELECT
    equipment_id,
    timestamp_utc,
    out_pct,
    fan_on,
    loop_on,
    COUNT(out_pct) OVER (
      PARTITION BY equipment_id ORDER BY timestamp_utc
      ROWS BETWEEN 11 PRECEDING AND CURRENT ROW
    ) AS n_samples,
    SUM(abs_step) OVER (
      PARTITION BY equipment_id ORDER BY timestamp_utc
      ROWS BETWEEN 11 PRECEDING AND CURRENT ROW
    ) AS tv,
    MAX(out_pct) OVER (
      PARTITION BY equipment_id ORDER BY timestamp_utc
      ROWS BETWEEN 11 PRECEDING AND CURRENT ROW
    )
      - MIN(out_pct) OVER (
      PARTITION BY equipment_id ORDER BY timestamp_utc
      ROWS BETWEEN 11 PRECEDING AND CURRENT ROW
    ) AS span,
    SUM(reversal_event) OVER (
      PARTITION BY equipment_id ORDER BY timestamp_utc
      ROWS BETWEEN 11 PRECEDING AND CURRENT ROW
    ) AS reversals
  FROM steps
),
base AS (
  SELECT
    equipment_id,
    timestamp_utc,
    CAST(CASE
      WHEN COALESCE(fan_on, 0) = 0 THEN 0
      WHEN loop_on IS NOT NULL AND loop_on <= 0.05 THEN 0
      WHEN out_pct IS NULL THEN 0
      WHEN n_samples < CAST(CEIL(12 * 80 / 100.0) AS INT) THEN 0
      WHEN span < 20 THEN 0
      WHEN tv < 500 THEN 0
      WHEN span <= 0 THEN 0
      WHEN (tv / (2.0 * NULLIF(span, 0))) < 2.5 THEN 0
      WHEN reversals < 4 THEN 0
      ELSE 1
    END AS INT) AS raw_fault
  FROM win
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
    CASE WHEN raw_fault = 1 AND streak_len >= 1 THEN 1 ELSE 0 END AS confirmed
  FROM ranked
)
SELECT
  equipment_id,
  SUM(confirmed) * 300 / 3600.0 AS fault_hours
FROM final
GROUP BY equipment_id;

EXECUTE fdd_rule_25;
DEALLOCATE fdd_rule_25;

-- FC4
PREPARE fdd_rule_26 AS
-- PostgreSQL adaptation. Render numeric template parameters with render_rule.py.
-- Inputs must be scoped to one tenant/site and cadence; see README.md.
-- fc4_os_hunting.sql — PID hunting (operating-state oscillation), GL36 fault 4
-- ΔOS > ΔOSmax during the clock hour: count how many times the AHU *enters* each
-- operating state within the hour and flag the whole hour when any state is
-- entered more than DELTA_OS_MAX times.
-- Operating states: 1 = min OA / heating, 2 = economizer, 3 = mechanical cooling
-- (0 = fan off, not counted).
WITH h AS (
  SELECT
    equipment_id,
    timestamp_utc,
    CASE WHEN oa_damper_pct IS NULL THEN NULL WHEN oa_damper_pct > 1.0 THEN oa_damper_pct / 100.0 ELSE oa_damper_pct END AS oa_d,
    CASE WHEN clg_valve_pct IS NULL THEN NULL WHEN clg_valve_pct > 1.0 THEN clg_valve_pct / 100.0 ELSE clg_valve_pct END AS clg,
    CASE
      WHEN fan_status IS NOT NULL THEN CASE WHEN fan_status > 0.05 THEN 1.0 ELSE 0.0 END
      WHEN fan_cmd IS NULL THEN NULL
      WHEN fan_cmd > 1.0 THEN fan_cmd / 100.0
      ELSE fan_cmd
    END AS fan,
    CASE
      WHEN 1 < 0.5 THEN 1
      WHEN fan_status IS NOT NULL THEN CASE WHEN fan_status > 0.05 THEN 1 ELSE 0 END
      WHEN fan_cmd IS NOT NULL THEN CASE WHEN (CASE WHEN fan_cmd > 1.0 THEN fan_cmd / 100.0 ELSE fan_cmd END) > 0.01 THEN 1 ELSE 0 END
      ELSE 1
    END AS fan_on
  FROM history
),
modes AS (
  SELECT
    equipment_id,
    timestamp_utc,
    DATE_TRUNC('hour', timestamp_utc) AS clock_hour,
    CASE
      WHEN fan IS NULL OR fan < 0.01 THEN 0
      WHEN clg IS NOT NULL AND clg > 0.1 THEN 3
      WHEN oa_d IS NOT NULL AND oa_d > 0.5 THEN 2
      ELSE 1
    END AS op_mode
  FROM h
),
entries AS (
  SELECT
    equipment_id,
    timestamp_utc,
    clock_hour,
    op_mode,
    CASE
      WHEN op_mode = 0 THEN 0
      WHEN LAG(op_mode) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc) IS NULL THEN 0
      WHEN op_mode <> LAG(op_mode) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc) THEN 1
      ELSE 0
    END AS is_entry
  FROM modes
),
hourly AS (
  SELECT
    equipment_id,
    timestamp_utc,
    SUM(CASE WHEN is_entry = 1 AND op_mode = 1 THEN 1 ELSE 0 END)
      OVER (PARTITION BY equipment_id, clock_hour) AS entries_min_oa,
    SUM(CASE WHEN is_entry = 1 AND op_mode = 2 THEN 1 ELSE 0 END)
      OVER (PARTITION BY equipment_id, clock_hour) AS entries_econ,
    SUM(CASE WHEN is_entry = 1 AND op_mode = 3 THEN 1 ELSE 0 END)
      OVER (PARTITION BY equipment_id, clock_hour) AS entries_mech
  FROM entries
),
base AS (
  SELECT
    equipment_id,
    timestamp_utc,
    CAST(CASE
      WHEN entries_min_oa > 5 THEN 1
      WHEN entries_econ > 5 THEN 1
      WHEN entries_mech > 5 THEN 1
      ELSE 0
    END AS INT) AS raw_fault
  FROM hourly
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
    CASE WHEN raw_fault = 1 AND streak_len >= 12 THEN 1 ELSE 0 END AS confirmed
  FROM ranked
)
, cov AS (
  SELECT equipment_id,
    100.0 * AVG(CAST(COALESCE(fan_on, 1) AS DOUBLE PRECISION)) AS cov_pct
  FROM h
  GROUP BY equipment_id
)
SELECT
  f.equipment_id,
  CASE
    WHEN 1 < 0.5 THEN SUM(f.confirmed) * 300 / 3600.0
    WHEN MAX(c.cov_pct) < 5 THEN 0.0
    ELSE SUM(f.confirmed) * 300 / 3600.0
  END AS fault_hours
FROM final f
LEFT JOIN cov c ON f.equipment_id = c.equipment_id
GROUP BY f.equipment_id;

EXECUTE fdd_rule_26;
DEALLOCATE fdd_rule_26;

-- FC5
PREPARE fdd_rule_27 AS
-- PostgreSQL adaptation. Render numeric template parameters with render_rule.py.
-- Inputs must be scoped to one tenant/site and cadence; see README.md.
-- fc5_sat_cold_heating.sql — SAT cold when heating commanded (GL36 D)
WITH h AS (
  SELECT
    equipment_id,
    timestamp_utc,
    sat, mat,
    CASE WHEN htg_valve_pct IS NULL THEN NULL WHEN htg_valve_pct > 1.0 THEN htg_valve_pct / 100.0 ELSE htg_valve_pct END AS htg,
    CASE WHEN fan_cmd IS NULL THEN NULL WHEN fan_cmd > 1.0 THEN fan_cmd / 100.0 ELSE fan_cmd END AS fan,
        CASE
      WHEN 1 < 0.5 THEN 1
      WHEN fan_status IS NOT NULL THEN CASE WHEN fan_status > 0.05 THEN 1 ELSE 0 END
      WHEN fan_cmd IS NOT NULL THEN CASE WHEN (CASE WHEN fan_cmd > 1.0 THEN fan_cmd / 100.0 ELSE fan_cmd END) > 0.01 THEN 1 ELSE 0 END
      ELSE 1
    END AS fan_on

  FROM history
),
base AS (
  SELECT
    equipment_id,
    timestamp_utc,
    CAST(CASE
      WHEN COALESCE(fan_on, 1) = 0 THEN 0
      WHEN COALESCE(mode_stable, 1) = 0 THEN 0
      WHEN sat IS NULL OR mat IS NULL OR htg IS NULL OR fan IS NULL THEN 0
      WHEN fan >= 0.01 AND htg > 0.01
       AND (sat + 1.15) <= (mat - 1.15 + 0.55) THEN 1
      ELSE 0
    END AS INT) AS raw_fault
  FROM (
  SELECT h.*,
    CASE
      WHEN COALESCE(fan_on, 1) = 0 THEN 0
      WHEN SUM(CASE WHEN COALESCE(fan_on, 1) = 0 THEN 1 ELSE 0 END) OVER (
        PARTITION BY equipment_id ORDER BY timestamp_utc
        ROWS BETWEEN 1 PRECEDING AND CURRENT ROW
      ) = 0 THEN 1
      ELSE 0
    END AS mode_stable
  FROM h
) h
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
    CASE WHEN raw_fault = 1 AND streak_len >= 2 THEN 1 ELSE 0 END AS confirmed
  FROM ranked
)
, cov AS (
  SELECT equipment_id,
    100.0 * AVG(CAST(COALESCE(fan_on, 1) AS DOUBLE PRECISION)) AS cov_pct
  FROM h
  GROUP BY equipment_id
)
SELECT
  f.equipment_id,
  CASE
    WHEN 1 < 0.5 THEN SUM(f.confirmed) * 300 / 3600.0
    WHEN MAX(c.cov_pct) < 5 THEN 0.0
    ELSE SUM(f.confirmed) * 300 / 3600.0
  END AS fault_hours
FROM final f
LEFT JOIN cov c ON f.equipment_id = c.equipment_id
GROUP BY f.equipment_id;

EXECUTE fdd_rule_27;
DEALLOCATE fdd_rule_27;

-- FC6
PREPARE fdd_rule_28 AS
-- PostgreSQL adaptation. Render numeric template parameters with render_rule.py.
-- Inputs must be scoped to one tenant/site and cadence; see README.md.
-- fc6_oa_frac_mismatch.sql — Estimated OA fraction mismatch (GL36 fault 6)
-- |RATavg − OATavg| >= ΔTmin AND |estimated OA% − design min OA%| > εF, where
-- design min OA% = MIN_CFM_DESIGN / total VAV airflow.
WITH h AS (
  SELECT
    equipment_id,
    timestamp_utc,
    mat, rat, oa_t, vav_total_flow,
    CASE WHEN fan_cmd IS NULL THEN NULL WHEN fan_cmd > 1.0 THEN fan_cmd / 100.0 ELSE fan_cmd END AS fan,
        CASE
      WHEN 1 < 0.5 THEN 1
      WHEN fan_status IS NOT NULL THEN CASE WHEN fan_status > 0.05 THEN 1 ELSE 0 END
      WHEN fan_cmd IS NOT NULL THEN CASE WHEN (CASE WHEN fan_cmd > 1.0 THEN fan_cmd / 100.0 ELSE fan_cmd END) > 0.01 THEN 1 ELSE 0 END
      ELSE 1
    END AS fan_on

  FROM history
),
base AS (
  SELECT
    equipment_id,
    timestamp_utc,
    CAST(CASE
      WHEN COALESCE(fan_on, 1) = 0 THEN 0
      WHEN COALESCE(mode_stable, 1) = 0 THEN 0
      WHEN mat IS NULL OR rat IS NULL OR oa_t IS NULL OR fan IS NULL THEN 0
      WHEN vav_total_flow IS NULL OR vav_total_flow <= 0.0 THEN 0
      WHEN fan < 0.01 THEN 0
      WHEN ABS(rat - oa_t) < 5 THEN 0
      WHEN ABS((mat - rat) / NULLIF(oa_t - rat, 0)
               - 5000 / NULLIF(vav_total_flow, 0)) > 0.15 THEN 1
      ELSE 0
    END AS INT) AS raw_fault
  FROM (
  SELECT h.*,
    CASE
      WHEN COALESCE(fan_on, 1) = 0 THEN 0
      WHEN SUM(CASE WHEN COALESCE(fan_on, 1) = 0 THEN 1 ELSE 0 END) OVER (
        PARTITION BY equipment_id ORDER BY timestamp_utc
        ROWS BETWEEN 1 PRECEDING AND CURRENT ROW
      ) = 0 THEN 1
      ELSE 0
    END AS mode_stable
  FROM h
) h
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
    CASE WHEN raw_fault = 1 AND streak_len >= 2 THEN 1 ELSE 0 END AS confirmed
  FROM ranked
)
, cov AS (
  SELECT equipment_id,
    100.0 * AVG(CAST(COALESCE(fan_on, 1) AS DOUBLE PRECISION)) AS cov_pct
  FROM h
  GROUP BY equipment_id
)
SELECT
  f.equipment_id,
  CASE
    WHEN 1 < 0.5 THEN SUM(f.confirmed) * 300 / 3600.0
    WHEN MAX(c.cov_pct) < 5 THEN 0.0
    ELSE SUM(f.confirmed) * 300 / 3600.0
  END AS fault_hours
FROM final f
LEFT JOIN cov c ON f.equipment_id = c.equipment_id
GROUP BY f.equipment_id;

EXECUTE fdd_rule_28;
DEALLOCATE fdd_rule_28;

-- FC14
PREPARE fdd_rule_29 AS
-- PostgreSQL adaptation. Render numeric template parameters with render_rule.py.
-- Inputs must be scoped to one tenant/site and cadence; see README.md.
-- fc14_chw_coil_dt_inactive.sql — CHW coil ΔT when inactive (GL36 L)
-- Prefer dedicated coil temps; fall back to MAT/SAT proxy when coil sensors absent.
WITH h AS (
  SELECT
    equipment_id,
    timestamp_utc,
    COALESCE(cooling_coil_entering_temp, mat) AS enter_t,
    COALESCE(cooling_coil_leaving_temp, sat) AS leave_t,
    CASE WHEN clg_valve_pct IS NULL THEN 0.0 WHEN clg_valve_pct > 1.0 THEN clg_valve_pct / 100.0 ELSE clg_valve_pct END AS clg,
    CASE WHEN oa_damper_pct IS NULL THEN 0.0 WHEN oa_damper_pct > 1.0 THEN oa_damper_pct / 100.0 ELSE oa_damper_pct END AS oa_d,
    CASE WHEN fan_cmd IS NULL THEN 0.0 WHEN fan_cmd > 1.0 THEN fan_cmd / 100.0 ELSE fan_cmd END AS fan,
        CASE
      WHEN 1 < 0.5 THEN 1
      WHEN fan_status IS NOT NULL THEN CASE WHEN fan_status > 0.05 THEN 1 ELSE 0 END
      WHEN fan_cmd IS NOT NULL THEN CASE WHEN (CASE WHEN fan_cmd > 1.0 THEN fan_cmd / 100.0 ELSE fan_cmd END) > 0.01 THEN 1 ELSE 0 END
      ELSE 1
    END AS fan_on
  FROM history
),
base AS (
  SELECT
    equipment_id,
    timestamp_utc,
    CAST(CASE
      WHEN COALESCE(fan_on, 1) = 0 THEN 0
      WHEN COALESCE(mode_stable, 1) = 0 THEN 0
      WHEN enter_t IS NULL OR leave_t IS NULL THEN 0
      WHEN fan < 0.01 THEN 0
      WHEN clg > 0.01 THEN 0
      WHEN ABS(enter_t - leave_t) >= SQRT(2.0 * 1.15 * 1.15) + 0.55 THEN 1
      ELSE 0
    END AS INT) AS raw_fault
  FROM (
  SELECT h.*,
    CASE
      WHEN COALESCE(fan_on, 1) = 0 THEN 0
      WHEN SUM(CASE WHEN COALESCE(fan_on, 1) = 0 THEN 1 ELSE 0 END) OVER (
        PARTITION BY equipment_id ORDER BY timestamp_utc
        ROWS BETWEEN 1 PRECEDING AND CURRENT ROW
      ) = 0 THEN 1
      ELSE 0
    END AS mode_stable
  FROM h
) h
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
    CASE WHEN raw_fault = 1 AND streak_len >= 2 THEN 1 ELSE 0 END AS confirmed
  FROM ranked
)
, cov AS (
  SELECT equipment_id,
    100.0 * AVG(CAST(COALESCE(fan_on, 1) AS DOUBLE PRECISION)) AS cov_pct
  FROM h
  GROUP BY equipment_id
)
SELECT
  f.equipment_id,
  CASE
    WHEN 1 < 0.5 THEN SUM(f.confirmed) * 300 / 3600.0
    WHEN MAX(c.cov_pct) < 5 THEN 0.0
    ELSE SUM(f.confirmed) * 300 / 3600.0
  END AS fault_hours
FROM final f
LEFT JOIN cov c ON f.equipment_id = c.equipment_id
GROUP BY f.equipment_id;

EXECUTE fdd_rule_29;
DEALLOCATE fdd_rule_29;

-- FC15
PREPARE fdd_rule_30 AS
-- PostgreSQL adaptation. Render numeric template parameters with render_rule.py.
-- Inputs must be scoped to one tenant/site and cadence; see README.md.
-- fc15_hw_coil_dt_inactive.sql — HW coil ΔT when inactive (GL36 M)
-- Prefer dedicated HW coil temps; fall back to MAT/SAT. Inactive gate uses
-- cooling-valve (pandas) when heating-valve is absent.
WITH h AS (
  SELECT
    equipment_id,
    timestamp_utc,
    COALESCE(heating_coil_entering_temp, mat) AS enter_t,
    COALESCE(heating_coil_leaving_temp, sat) AS leave_t,
    CASE WHEN htg_valve_pct IS NULL THEN 0.0 WHEN htg_valve_pct > 1.0 THEN htg_valve_pct / 100.0 ELSE htg_valve_pct END AS htg,
    CASE WHEN clg_valve_pct IS NULL THEN 0.0 WHEN clg_valve_pct > 1.0 THEN clg_valve_pct / 100.0 ELSE clg_valve_pct END AS clg,
    CASE WHEN fan_cmd IS NULL THEN 0.0 WHEN fan_cmd > 1.0 THEN fan_cmd / 100.0 ELSE fan_cmd END AS fan,
        CASE
      WHEN 1 < 0.5 THEN 1
      WHEN fan_status IS NOT NULL THEN CASE WHEN fan_status > 0.05 THEN 1 ELSE 0 END
      WHEN fan_cmd IS NOT NULL THEN CASE WHEN (CASE WHEN fan_cmd > 1.0 THEN fan_cmd / 100.0 ELSE fan_cmd END) > 0.01 THEN 1 ELSE 0 END
      ELSE 1
    END AS fan_on
  FROM history
),
base AS (
  SELECT
    equipment_id,
    timestamp_utc,
    CAST(CASE
      WHEN COALESCE(fan_on, 1) = 0 THEN 0
      WHEN COALESCE(mode_stable, 1) = 0 THEN 0
      WHEN enter_t IS NULL OR leave_t IS NULL THEN 0
      WHEN fan < 0.01 THEN 0
      WHEN htg > 0.01 THEN 0
      WHEN clg > 0.01 THEN 0
      WHEN ABS(enter_t - leave_t) >= SQRT(2.0 * 1.15 * 1.15) + 0.55 THEN 1
      ELSE 0
    END AS INT) AS raw_fault
  FROM (
  SELECT h.*,
    CASE
      WHEN COALESCE(fan_on, 1) = 0 THEN 0
      WHEN SUM(CASE WHEN COALESCE(fan_on, 1) = 0 THEN 1 ELSE 0 END) OVER (
        PARTITION BY equipment_id ORDER BY timestamp_utc
        ROWS BETWEEN 1 PRECEDING AND CURRENT ROW
      ) = 0 THEN 1
      ELSE 0
    END AS mode_stable
  FROM h
) h
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
    CASE WHEN raw_fault = 1 AND streak_len >= 2 THEN 1 ELSE 0 END AS confirmed
  FROM ranked
)
, cov AS (
  SELECT equipment_id,
    100.0 * AVG(CAST(COALESCE(fan_on, 1) AS DOUBLE PRECISION)) AS cov_pct
  FROM h
  GROUP BY equipment_id
)
SELECT
  f.equipment_id,
  CASE
    WHEN 1 < 0.5 THEN SUM(f.confirmed) * 300 / 3600.0
    WHEN MAX(c.cov_pct) < 5 THEN 0.0
    ELSE SUM(f.confirmed) * 300 / 3600.0
  END AS fault_hours
FROM final f
LEFT JOIN cov c ON f.equipment_id = c.equipment_id
GROUP BY f.equipment_id;

EXECUTE fdd_rule_30;
DEALLOCATE fdd_rule_30;

-- AHU-SATDEV
PREPARE fdd_rule_31 AS
-- PostgreSQL adaptation. Render numeric template parameters with render_rule.py.
-- Inputs must be scoped to one tenant/site and cadence; see README.md.
-- ahu_satdev.sql — SAT deviation from setpoint (fan_running + confirm)
-- Gate: fan-on from fan_status then fan_cmd. Missing fan stays off
-- (do not ELSE 1 / COALESCE to on — that invents on-hours).
WITH h AS (
  SELECT
    equipment_id,
    timestamp_utc,
    sat,
    sat_sp,
    fan_cmd,
    fan_status,
    CASE
      WHEN fan_status IS NOT NULL THEN CASE WHEN fan_status > 0.05 THEN 1 ELSE 0 END
      WHEN fan_cmd IS NOT NULL THEN CASE WHEN (CASE WHEN fan_cmd > 1.0 THEN fan_cmd / 100.0 ELSE fan_cmd END) > 0.01 THEN 1 ELSE 0 END
      ELSE 0
    END AS fan_on
  FROM history
),
base AS (
  SELECT
    equipment_id,
    timestamp_utc,
    CAST(CASE
      WHEN COALESCE(fan_on, 0) = 0 THEN 0
      WHEN sat IS NULL OR sat_sp IS NULL THEN 0
      WHEN ABS(sat - sat_sp) > 5 THEN 1
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
    CASE WHEN raw_fault = 1 AND streak_len >= 2 THEN 1 ELSE 0 END AS confirmed
  FROM ranked
)
SELECT
  equipment_id,
  SUM(confirmed) * 300 / 3600.0 AS fault_hours
FROM final
GROUP BY equipment_id;

EXECUTE fdd_rule_31;
DEALLOCATE fdd_rule_31;

-- AHU-DUCTHI
PREPARE fdd_rule_32 AS
-- PostgreSQL adaptation. Render numeric template parameters with render_rule.py.
-- Inputs must be scoped to one tenant/site and cadence; see README.md.
-- ahu_ducthi.sql — Duct static pressure high
-- Equation: static > SP + DUCT_HIGH_MARGIN.
-- Gate: fan-on from fan_status then fan_cmd. Missing fan stays NULL
-- (do not ELSE 1). Pressure-on substitutes only when fan proof is absent,
-- never when status/cmd is proven 0 (frozen overnight static).
WITH h AS (
  SELECT
    equipment_id,
    timestamp_utc,
    duct_static, duct_static_sp,
    CASE WHEN fan_cmd IS NULL THEN NULL WHEN fan_cmd > 1.0 THEN fan_cmd / 100.0 ELSE fan_cmd END AS fan,
    CASE
      WHEN fan_status IS NOT NULL THEN CASE WHEN fan_status > 0.05 THEN 1 ELSE 0 END
      WHEN fan_cmd IS NOT NULL THEN CASE WHEN (CASE WHEN fan_cmd > 1.0 THEN fan_cmd / 100.0 ELSE fan_cmd END) > 0.01 THEN 1 ELSE 0 END
      ELSE NULL
    END AS fan_on
  FROM history
),
base AS (
  SELECT
    equipment_id,
    timestamp_utc,
    CAST(CASE
      WHEN duct_static IS NULL OR duct_static_sp IS NULL THEN 0
      WHEN fan_on = 0 THEN 0
      WHEN fan_on = 1 AND duct_static > duct_static_sp + 0.25 THEN 1
      WHEN fan_on IS NULL
           AND ABS(duct_static) > 0.2
           AND duct_static > duct_static_sp + 0.25 THEN 1
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
    CASE WHEN raw_fault = 1 AND streak_len >= 1 THEN 1 ELSE 0 END AS confirmed
  FROM ranked
)
SELECT
  equipment_id,
  SUM(confirmed) * 300 / 3600.0 AS fault_hours
FROM final
GROUP BY equipment_id;

EXECUTE fdd_rule_32;
DEALLOCATE fdd_rule_32;

-- AHU-SIMUL
PREPARE fdd_rule_33 AS
-- PostgreSQL adaptation. Render numeric template parameters with render_rule.py.
-- Inputs must be scoped to one tenant/site and cadence; see README.md.
-- ahu_simul.sql — Heating and cooling simultaneous
WITH h AS (
  SELECT
    equipment_id,
    timestamp_utc,
    CASE WHEN htg_valve_pct IS NULL THEN NULL WHEN htg_valve_pct > 1.0 THEN htg_valve_pct / 100.0 ELSE htg_valve_pct END AS htg,
    CASE WHEN clg_valve_pct IS NULL THEN NULL WHEN clg_valve_pct > 1.0 THEN clg_valve_pct / 100.0 ELSE clg_valve_pct END AS clg,
    fan_cmd,
    fan_status,
    CASE
      WHEN fan_status IS NOT NULL THEN CASE WHEN fan_status > 0.05 THEN 1 ELSE 0 END
      WHEN fan_cmd IS NOT NULL THEN CASE WHEN (CASE WHEN fan_cmd > 1.0 THEN fan_cmd / 100.0 ELSE fan_cmd END) > 0.01 THEN 1 ELSE 0 END
      ELSE 1
    END AS fan_on

  FROM history
),
base AS (
  SELECT
    equipment_id,
    timestamp_utc,
    CAST(CASE
      WHEN COALESCE(fan_on, 1) = 0 THEN 0
      WHEN htg IS NULL OR clg IS NULL THEN 0
      WHEN htg > 0.1 AND clg > 0.1 THEN 1
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
    CASE WHEN raw_fault = 1 AND streak_len >= 1 THEN 1 ELSE 0 END AS confirmed
  FROM ranked
)
SELECT
  equipment_id,
  SUM(confirmed) * 300 / 3600.0 AS fault_hours
FROM final
GROUP BY equipment_id;

EXECUTE fdd_rule_33;
DEALLOCATE fdd_rule_33;

-- ECON-3
PREPARE fdd_rule_34 AS
-- PostgreSQL adaptation. Render numeric template parameters with render_rule.py.
-- Inputs must be scoped to one tenant/site and cadence; see README.md.
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
      WHEN web_oa_t >= 60 AND web_oa_t < 72 AND web_oa_dp < 60
       AND clg > 0.01 AND oa_d < 0.9 THEN 1
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
    CASE WHEN raw_fault = 1 AND streak_len >= 1 THEN 1 ELSE 0 END AS confirmed
  FROM ranked
)
SELECT
  equipment_id,
  SUM(confirmed) * 300 / 3600.0 AS fault_hours
FROM final
GROUP BY equipment_id;

EXECUTE fdd_rule_34;
DEALLOCATE fdd_rule_34;

-- ECON-5
PREPARE fdd_rule_35 AS
-- PostgreSQL adaptation. Render numeric template parameters with render_rule.py.
-- Inputs must be scoped to one tenant/site and cadence; see README.md.
-- econ5_preheat_over.sql — Preheat over-conditioning (matches vibe19 econ5)
-- Target = OAT when OAT > SAT SP; else SAT SP. Fault when preheat exceeds target by ΔT
-- while heating valve is open.
WITH h AS (
  SELECT
    equipment_id,
    timestamp_utc,
    preheat_leave_t, sat_sp, oa_t,
    CASE WHEN htg_valve_pct IS NULL THEN 0.0 WHEN htg_valve_pct > 1.0 THEN htg_valve_pct / 100.0 ELSE htg_valve_pct END AS htg,
    fan_cmd,
    fan_status,
    CASE
      WHEN fan_status IS NOT NULL THEN CASE WHEN fan_status > 0.05 THEN 1 ELSE 0 END
      WHEN fan_cmd IS NOT NULL THEN CASE WHEN (CASE WHEN fan_cmd > 1.0 THEN fan_cmd / 100.0 ELSE fan_cmd END) > 0.01 THEN 1 ELSE 0 END
      ELSE 1
    END AS fan_on

  FROM history
),
base AS (
  SELECT
    equipment_id,
    timestamp_utc,
    CAST(CASE
      WHEN COALESCE(fan_on, 1) = 0 THEN 0
      WHEN preheat_leave_t IS NULL OR sat_sp IS NULL OR oa_t IS NULL THEN 0
      WHEN htg > 0.01 AND (
        (oa_t > sat_sp AND preheat_leave_t - oa_t > 2.2)
        OR (oa_t < sat_sp AND preheat_leave_t - sat_sp > 2.2)
      ) THEN 1
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
    CASE WHEN raw_fault = 1 AND streak_len >= 2 THEN 1 ELSE 0 END AS confirmed
  FROM ranked
)
SELECT
  equipment_id,
  SUM(confirmed) * 300 / 3600.0 AS fault_hours
FROM final
GROUP BY equipment_id;

EXECUTE fdd_rule_35;
DEALLOCATE fdd_rule_35;

-- ECON-6
PREPARE fdd_rule_36 AS
-- PostgreSQL adaptation. Render numeric template parameters with render_rule.py.
-- Inputs must be scoped to one tenant/site and cadence; see README.md.
-- econ6_econ_freezing.sql — Economizing in freezing weather
-- Web dry-bulb: prefer equipment web_oa_t; else weather sidecar. Never BAS oa_t.
WITH wx AS (
  SELECT
    timestamp_utc,
    MAX(web_oa_t) AS wx_web_oa_t
  FROM weather
  GROUP BY timestamp_utc
),
h AS (
  SELECT
    h.equipment_id,
    h.timestamp_utc,
    COALESCE(h.web_oa_t, wx.wx_web_oa_t) AS web_oa_t,
    CASE WHEN h.oa_damper_pct IS NULL THEN NULL WHEN h.oa_damper_pct > 1.0 THEN h.oa_damper_pct / 100.0 ELSE h.oa_damper_pct END AS oa_d,
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
      WHEN web_oa_t IS NULL OR oa_d IS NULL THEN 0
      WHEN web_oa_t < 25 AND oa_d > 0.25 THEN 1
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
    CASE WHEN raw_fault = 1 AND streak_len >= 2 THEN 1 ELSE 0 END AS confirmed
  FROM ranked
)
SELECT
  equipment_id,
  SUM(confirmed) * 300 / 3600.0 AS fault_hours
FROM final
GROUP BY equipment_id;

EXECUTE fdd_rule_36;
DEALLOCATE fdd_rule_36;

-- ECON-7
PREPARE fdd_rule_37 AS
-- PostgreSQL adaptation. Render numeric template parameters with render_rule.py.
-- Inputs must be scoped to one tenant/site and cadence; see README.md.
-- econ7_ok_not_economizing.sql — Economizer OK but not economizing
-- Web DB+DP: prefer equipment web_oa_*; else weather sidecar. Never BAS oa_t.
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
      WHEN web_oa_t >= 35 AND web_oa_t < 72 AND web_oa_dp < 60
       AND clg > 0.05 AND oa_d < 0.5 THEN 1
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
    CASE WHEN raw_fault = 1 AND streak_len >= 2 THEN 1 ELSE 0 END AS confirmed
  FROM ranked
)
SELECT
  equipment_id,
  SUM(confirmed) * 300 / 3600.0 AS fault_hours
FROM final
GROUP BY equipment_id;

EXECUTE fdd_rule_37;
DEALLOCATE fdd_rule_37;

-- MECH-OAT-1
PREPARE fdd_rule_38 AS
-- PostgreSQL adaptation. Render numeric template parameters with render_rule.py.
-- Inputs must be scoped to one tenant/site and cadence; see README.md.
-- mech_oat_1.sql — Mechanical cooling below 60°F web OAT
-- Proof: chiller_status OR cooling valve (pandas mechanical_proof_mask).
WITH h AS (
  SELECT
    equipment_id,
    timestamp_utc,
    web_oa_t,
    CASE WHEN clg_valve_pct IS NULL THEN NULL WHEN clg_valve_pct > 1.0 THEN clg_valve_pct / 100.0 ELSE clg_valve_pct END AS clg,
    CASE WHEN chiller_status IS NULL THEN NULL WHEN chiller_status > 0.05 THEN 1.0 ELSE 0.0 END AS chill_on
  FROM history
),
base AS (
  SELECT
    equipment_id,
    timestamp_utc,
    CAST(CASE
      WHEN web_oa_t IS NULL THEN 0
      WHEN web_oa_t >= 60 THEN 0
      WHEN chill_on IS NOT NULL AND chill_on > 0.05 THEN 1
      WHEN clg IS NOT NULL AND clg > 0.05 THEN 1
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
    CASE WHEN raw_fault = 1 AND streak_len >= 2 THEN 1 ELSE 0 END AS confirmed
  FROM ranked
)
SELECT
  equipment_id,
  SUM(confirmed) * 300 / 3600.0 AS fault_hours
FROM final
GROUP BY equipment_id;

EXECUTE fdd_rule_38;
DEALLOCATE fdd_rule_38;

-- CMD-1
PREPARE fdd_rule_39 AS
-- PostgreSQL adaptation. Render numeric template parameters with render_rule.py.
-- Inputs must be scoped to one tenant/site and cadence; see README.md.
-- cmd1_fan_mismatch.sql — Fan cmd/status mismatch
WITH h AS (
  SELECT
    equipment_id,
    timestamp_utc,
    CASE WHEN fan_cmd IS NULL THEN NULL WHEN fan_cmd > 1.0 THEN fan_cmd / 100.0 ELSE fan_cmd END AS fan,
    fan_status
  FROM history
),
base AS (
  SELECT
    equipment_id,
    timestamp_utc,
        CAST(CASE
          WHEN fan IS NULL OR fan_status IS NULL THEN 0
          WHEN (fan >= 0.05) <> (fan_status > 0.5) THEN 1
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
    CASE WHEN raw_fault = 1 AND streak_len >= 2 THEN 1 ELSE 0 END AS confirmed
  FROM ranked
)
SELECT
  equipment_id,
  SUM(confirmed) * 300 / 3600.0 AS fault_hours
FROM final
GROUP BY equipment_id;

EXECUTE fdd_rule_39;
DEALLOCATE fdd_rule_39;

-- OA-1
PREPARE fdd_rule_40 AS
-- PostgreSQL adaptation. Render numeric template parameters with render_rule.py.
-- Inputs must be scoped to one tenant/site and cadence; see README.md.
-- oa1_low_oa_frac.sql — Low OA fraction
WITH h AS (
  SELECT
    equipment_id,
    timestamp_utc,
    mat, rat, oa_t,
    CASE WHEN fan_cmd IS NULL THEN NULL WHEN fan_cmd > 1.0 THEN fan_cmd / 100.0 ELSE fan_cmd END AS fan,
    CASE
      WHEN fan_status IS NOT NULL THEN CASE WHEN fan_status > 0.05 THEN 1 ELSE 0 END
      WHEN fan_cmd IS NOT NULL THEN CASE WHEN (CASE WHEN fan_cmd > 1.0 THEN fan_cmd / 100.0 ELSE fan_cmd END) > 0.01 THEN 1 ELSE 0 END
      ELSE 1
    END AS fan_on

  FROM history
),
base AS (
  SELECT
    equipment_id,
    timestamp_utc,
    CAST(CASE
      WHEN COALESCE(fan_on, 1) = 0 THEN 0
      WHEN mat IS NULL OR rat IS NULL OR oa_t IS NULL THEN 0
      WHEN ABS(rat - oa_t) <= 2.2 THEN 0
      WHEN (mat - rat) / NULLIF(oa_t - rat, 0) < 0.15
       AND fan IS NOT NULL AND fan >= 0.05 THEN 1
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
    CASE WHEN raw_fault = 1 AND streak_len >= 3 THEN 1 ELSE 0 END AS confirmed
  FROM ranked
)
SELECT
  equipment_id,
  SUM(confirmed) * 300 / 3600.0 AS fault_hours
FROM final
GROUP BY equipment_id;

EXECUTE fdd_rule_40;
DEALLOCATE fdd_rule_40;

-- DMP-1
PREPARE fdd_rule_41 AS
-- PostgreSQL adaptation. Render numeric template parameters with render_rule.py.
-- Inputs must be scoped to one tenant/site and cadence; see README.md.
-- dmp1_oa_damper_leak.sql — OA damper leakage
WITH h AS (
  SELECT
    equipment_id,
    timestamp_utc,
    oa_t, mat,
    CASE WHEN oa_damper_pct IS NULL THEN NULL WHEN oa_damper_pct > 1.0 THEN oa_damper_pct / 100.0 ELSE oa_damper_pct END AS oa_d,
    fan_cmd,
    fan_status,
    CASE
      WHEN fan_status IS NOT NULL THEN CASE WHEN fan_status > 0.05 THEN 1 ELSE 0 END
      WHEN fan_cmd IS NOT NULL THEN CASE WHEN (CASE WHEN fan_cmd > 1.0 THEN fan_cmd / 100.0 ELSE fan_cmd END) > 0.01 THEN 1 ELSE 0 END
      ELSE 1
    END AS fan_on

  FROM history
),
base AS (
  SELECT
    equipment_id,
    timestamp_utc,
    CAST(CASE
      WHEN COALESCE(fan_on, 1) = 0 THEN 0
      WHEN oa_d IS NULL OR oa_t IS NULL OR mat IS NULL THEN 0
      WHEN oa_d <= 0.05 AND ABS(mat - oa_t) < 2 THEN 1
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
    CASE WHEN raw_fault = 1 AND streak_len >= 3 THEN 1 ELSE 0 END AS confirmed
  FROM ranked
)
SELECT
  equipment_id,
  SUM(confirmed) * 300 / 3600.0 AS fault_hours
FROM final
GROUP BY equipment_id;

EXECUTE fdd_rule_41;
DEALLOCATE fdd_rule_41;

-- VLV-1
PREPARE fdd_rule_42 AS
-- PostgreSQL adaptation. Render numeric template parameters with render_rule.py.
-- Inputs must be scoped to one tenant/site and cadence; see README.md.
-- vlv1_clg_valve_leak.sql — Cooling valve leakage
WITH h AS (
  SELECT
    equipment_id,
    timestamp_utc,
    sat, sat_sp, mat,
    CASE WHEN clg_valve_pct IS NULL THEN NULL WHEN clg_valve_pct > 1.0 THEN clg_valve_pct / 100.0 ELSE clg_valve_pct END AS clg,
    fan_cmd,
    fan_status,
    CASE
      WHEN fan_status IS NOT NULL THEN CASE WHEN fan_status > 0.05 THEN 1 ELSE 0 END
      WHEN fan_cmd IS NOT NULL THEN CASE WHEN (CASE WHEN fan_cmd > 1.0 THEN fan_cmd / 100.0 ELSE fan_cmd END) > 0.01 THEN 1 ELSE 0 END
      ELSE 1
    END AS fan_on

  FROM history
),
base AS (
  SELECT
    equipment_id,
    timestamp_utc,
    CAST(CASE
      WHEN COALESCE(fan_on, 1) = 0 THEN 0
      WHEN clg IS NULL OR sat IS NULL THEN 0
      WHEN clg <= 0.05 AND (
        (sat_sp IS NOT NULL AND sat < sat_sp - 2)
        OR (mat IS NOT NULL AND sat < mat - 2)
      ) THEN 1
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
    CASE WHEN raw_fault = 1 AND streak_len >= 3 THEN 1 ELSE 0 END AS confirmed
  FROM ranked
)
SELECT
  equipment_id,
  SUM(confirmed) * 300 / 3600.0 AS fault_hours
FROM final
GROUP BY equipment_id;

EXECUTE fdd_rule_42;
DEALLOCATE fdd_rule_42;

-- VAV-3
PREPARE fdd_rule_43 AS
-- PostgreSQL adaptation. Render numeric template parameters with render_rule.py.
-- Inputs must be scoped to one tenant/site and cadence; see README.md.
-- vav3_excessive_reheat.sql — Excessive reheat during warm weather
WITH h AS (
  SELECT
    equipment_id,
    timestamp_utc,
    oa_t, zone_flow,
    CASE WHEN reheat_valve_pct IS NULL THEN NULL WHEN reheat_valve_pct > 1.0 THEN reheat_valve_pct / 100.0 ELSE reheat_valve_pct END AS rh,
    fan_cmd,
    fan_status,
    CASE
      WHEN fan_status IS NOT NULL THEN CASE WHEN fan_status > 0.05 THEN 1 ELSE 0 END
      WHEN fan_cmd IS NOT NULL THEN CASE WHEN (CASE WHEN fan_cmd > 1.0 THEN fan_cmd / 100.0 ELSE fan_cmd END) > 0.01 THEN 1 ELSE 0 END
      ELSE 1
    END AS fan_on

  FROM history
),
base AS (
  SELECT
    equipment_id,
    timestamp_utc,
    CAST(CASE
      WHEN COALESCE(fan_on, 0) = 0 THEN 0
      WHEN oa_t IS NULL OR rh IS NULL THEN 0
      WHEN COALESCE(zone_flow, 0) > 25
       AND oa_t > 78 AND rh > 0.52 THEN 1
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
    CASE WHEN raw_fault = 1 AND streak_len >= 1 THEN 1 ELSE 0 END AS confirmed
  FROM ranked
)
SELECT
  equipment_id,
  SUM(confirmed) * 300 / 3600.0 AS fault_hours
FROM final
GROUP BY equipment_id;

EXECUTE fdd_rule_43;
DEALLOCATE fdd_rule_43;

-- VAV-4
PREPARE fdd_rule_44 AS
-- PostgreSQL adaptation. Render numeric template parameters with render_rule.py.
-- Inputs must be scoped to one tenant/site and cadence; see README.md.
-- vav4_damper_full_open.sql — sequential sustain then confirm (pandas vav4).
-- Stage 1: air-on and damper > FULL_OPEN for SUSTAIN_ROWS consecutive samples.
-- Stage 2: confirm that sustained mask for CONFIRM_ROWS (not max of the two).
WITH h AS (
  SELECT
    equipment_id,
    timestamp_utc,
    zone_flow,
    CASE WHEN damper_pct IS NULL THEN NULL WHEN damper_pct > 1.0 THEN damper_pct / 100.0 ELSE damper_pct END AS dmp,
    fan_cmd,
    fan_status,
    CASE
      WHEN fan_status IS NOT NULL THEN CASE WHEN fan_status > 0.05 THEN 1 ELSE 0 END
      WHEN fan_cmd IS NOT NULL THEN CASE WHEN (CASE WHEN fan_cmd > 1.0 THEN fan_cmd / 100.0 ELSE fan_cmd END) > 0.01 THEN 1 ELSE 0 END
      WHEN zone_flow IS NOT NULL AND zone_flow > 25 THEN 1
      ELSE 1
    END AS fan_on
  FROM history
),
cond AS (
  SELECT
    equipment_id,
    timestamp_utc,
    CAST(CASE
      WHEN COALESCE(fan_on, 0) = 0 THEN 0
      WHEN dmp IS NULL THEN 0
      WHEN COALESCE(zone_flow, 0) > 25 AND dmp > 0.975 THEN 1
      ELSE 0
    END AS INT) AS cond_fault
  FROM h
),
lagged1 AS (
  SELECT
    *,
    CASE
      WHEN cond_fault = LAG(cond_fault) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc)
      THEN 0 ELSE 1
    END AS is_new1
  FROM cond
),
grp1 AS (
  SELECT
    *,
    SUM(is_new1) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS UNBOUNDED PRECEDING) AS streak1
  FROM lagged1
),
sustained AS (
  SELECT
    equipment_id,
    timestamp_utc,
    CAST(CASE
      WHEN cond_fault = 1
       AND ROW_NUMBER() OVER (PARTITION BY equipment_id, streak1 ORDER BY timestamp_utc)
           >= CAST(CEIL(1.5 * 3600.0 / 300) AS INT)
      THEN 1 ELSE 0
    END AS INT) AS sustained_fault
  FROM grp1
),
lagged2 AS (
  SELECT
    *,
    CASE
      WHEN sustained_fault = LAG(sustained_fault) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc)
      THEN 0 ELSE 1
    END AS is_new2
  FROM sustained
),
grp2 AS (
  SELECT
    *,
    SUM(is_new2) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS UNBOUNDED PRECEDING) AS streak2
  FROM lagged2
),
final AS (
  SELECT
    equipment_id,
    CAST(CASE
      WHEN sustained_fault = 1
       AND ROW_NUMBER() OVER (PARTITION BY equipment_id, streak2 ORDER BY timestamp_utc) >= 3
      THEN 1 ELSE 0
    END AS INT) AS confirmed
  FROM grp2
)
SELECT
  equipment_id,
  SUM(confirmed) * 300 / 3600.0 AS fault_hours
FROM final
GROUP BY equipment_id;

EXECUTE fdd_rule_44;
DEALLOCATE fdd_rule_44;

-- VAV-5
PREPARE fdd_rule_45 AS
-- PostgreSQL adaptation. Render numeric template parameters with render_rule.py.
-- Inputs must be scoped to one tenant/site and cadence; see README.md.
-- vav5_airflow_bias.sql — Airflow sensor bias
WITH h AS (
  SELECT
    equipment_id,
    timestamp_utc,
    zone_flow,
    CASE WHEN damper_pct IS NULL THEN NULL WHEN damper_pct > 1.0 THEN damper_pct / 100.0 ELSE damper_pct END AS dmp,
    fan_cmd,
    fan_status,
    CASE
      WHEN fan_status IS NOT NULL THEN CASE WHEN fan_status > 0.05 THEN 1 ELSE 0 END
      WHEN fan_cmd IS NOT NULL THEN CASE WHEN (CASE WHEN fan_cmd > 1.0 THEN fan_cmd / 100.0 ELSE fan_cmd END) > 0.01 THEN 1 ELSE 0 END
      ELSE 1
    END AS fan_on

  FROM history
),
base AS (
  SELECT
    equipment_id,
    timestamp_utc,
    CAST(CASE
      WHEN COALESCE(fan_on, 0) = 0 THEN 0
      WHEN zone_flow IS NULL OR dmp IS NULL THEN 0
      WHEN zone_flow > 50 AND dmp < 0.1 THEN 1
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
    CASE WHEN raw_fault = 1 AND streak_len >= 3 THEN 1 ELSE 0 END AS confirmed
  FROM ranked
)
SELECT
  equipment_id,
  SUM(confirmed) * 300 / 3600.0 AS fault_hours
FROM final
GROUP BY equipment_id;

EXECUTE fdd_rule_45;
DEALLOCATE fdd_rule_45;

-- VAV-6
PREPARE fdd_rule_46 AS
-- PostgreSQL adaptation. Render numeric template parameters with render_rule.py.
-- Inputs must be scoped to one tenant/site and cadence; see README.md.
-- vav6_reheat_free_cool.sql — reheat open while OA is cool enough for free cooling
WITH h AS (
  SELECT
    equipment_id,
    timestamp_utc,
    oa_t,
    clg_available,
    CASE WHEN reheat_valve_pct IS NULL THEN NULL
         WHEN reheat_valve_pct > 1.0 THEN reheat_valve_pct / 100.0
         ELSE reheat_valve_pct END AS rh
  FROM history
),
base AS (
  SELECT
    equipment_id,
    timestamp_utc,
    CAST(CASE
      WHEN oa_t IS NULL OR rh IS NULL THEN 0
      WHEN COALESCE(clg_available, 1) > 0.05
       AND oa_t < 65 AND rh > 0.25 THEN 1
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
    CASE WHEN raw_fault = 1 AND streak_len >= 3 THEN 1 ELSE 0 END AS confirmed
  FROM ranked
)
SELECT
  equipment_id,
  SUM(confirmed) * 300 / 3600.0 AS fault_hours
FROM final
GROUP BY equipment_id;

EXECUTE fdd_rule_46;
DEALLOCATE fdd_rule_46;

-- VAV-REHEAT
PREPARE fdd_rule_47 AS
-- PostgreSQL adaptation. Render numeric template parameters with render_rule.py.
-- Inputs must be scoped to one tenant/site and cadence; see README.md.
-- vav_reheat.sql — Reheat valve stuck / no temp rise
WITH h AS (
  SELECT
    equipment_id,
    timestamp_utc,
    vav_discharge_t, vav_inlet_t, zone_flow,
    CASE WHEN reheat_valve_pct IS NULL THEN NULL WHEN reheat_valve_pct > 1.0 THEN reheat_valve_pct / 100.0 ELSE reheat_valve_pct END AS rh,
    fan_cmd,
    fan_status,
    CASE
      WHEN fan_status IS NOT NULL THEN CASE WHEN fan_status > 0.05 THEN 1 ELSE 0 END
      WHEN fan_cmd IS NOT NULL THEN CASE WHEN (CASE WHEN fan_cmd > 1.0 THEN fan_cmd / 100.0 ELSE fan_cmd END) > 0.01 THEN 1 ELSE 0 END
      ELSE 1
    END AS fan_on

  FROM history
),
base AS (
  SELECT
    equipment_id,
    timestamp_utc,
    CAST(CASE
      WHEN COALESCE(fan_on, 0) = 0 THEN 0
      WHEN rh IS NULL OR vav_discharge_t IS NULL OR vav_inlet_t IS NULL THEN 0
      WHEN COALESCE(zone_flow, 0) > 25
       AND rh > 0.3
       AND (vav_discharge_t - vav_inlet_t) < 3 THEN 1
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
    CASE WHEN raw_fault = 1 AND streak_len >= 3 THEN 1 ELSE 0 END AS confirmed
  FROM ranked
)
SELECT
  equipment_id,
  SUM(confirmed) * 300 / 3600.0 AS fault_hours
FROM final
GROUP BY equipment_id;

EXECUTE fdd_rule_47;
DEALLOCATE fdd_rule_47;

-- VAV-AHU-LEAVE
PREPARE fdd_rule_48 AS
-- PostgreSQL adaptation. Render numeric template parameters with render_rule.py.
-- Inputs must be scoped to one tenant/site and cadence; see README.md.
-- vav_ahu_leave.sql — VAV leave vs parent AHU SAT (fedBy)
WITH h AS (
  SELECT
    equipment_id,
    timestamp_utc,
    vav_discharge_t,
    ahu_sat,
    zone_flow,
    fan_cmd,
    fan_status,
    CASE
      WHEN fan_status IS NOT NULL THEN CASE WHEN fan_status > 0.05 THEN 1 ELSE 0 END
      WHEN fan_cmd IS NOT NULL THEN CASE WHEN (CASE WHEN fan_cmd > 1.0 THEN fan_cmd / 100.0 ELSE fan_cmd END) > 0.01 THEN 1 ELSE 0 END
      ELSE 1
    END AS fan_on
  FROM history
),
base AS (
  SELECT
    equipment_id,
    timestamp_utc,
    CAST(CASE
      WHEN COALESCE(fan_on, 0) = 0 THEN 0
      WHEN vav_discharge_t IS NULL OR ahu_sat IS NULL THEN 0
      WHEN COALESCE(zone_flow, 0) > 25
       AND ABS(vav_discharge_t - ahu_sat) > 8 THEN 1
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
    CASE WHEN raw_fault = 1 AND streak_len >= 3 THEN 1 ELSE 0 END AS confirmed
  FROM ranked
)
SELECT
  equipment_id,
  SUM(confirmed) * 300 / 3600.0 AS fault_hours
FROM final
GROUP BY equipment_id;

EXECUTE fdd_rule_48;
DEALLOCATE fdd_rule_48;

-- VAV-7
PREPARE fdd_rule_49 AS
-- PostgreSQL adaptation. Render numeric template parameters with render_rule.py.
-- Inputs must be scoped to one tenant/site and cadence; see README.md.
-- vav7_min_airflow.sql — three pandas branches: under-min, fixed-high flow, high min SP.
-- Rolling windows use poll-derived 12 (1h sample count), matching pandas.
WITH h AS (
  SELECT
    equipment_id,
    timestamp_utc,
    zone_flow,
    min_flow_sp,
    fan_cmd,
    fan_status,
    CASE
      WHEN fan_status IS NOT NULL THEN CASE WHEN fan_status > 0.05 THEN 1 ELSE 0 END
      WHEN fan_cmd IS NOT NULL THEN CASE WHEN (CASE WHEN fan_cmd > 1.0 THEN fan_cmd / 100.0 ELSE fan_cmd END) > 0.01 THEN 1 ELSE 0 END
      WHEN zone_flow IS NOT NULL AND zone_flow > 25 THEN 1
      ELSE 1
    END AS fan_on
  FROM history
),
rolled AS (
  SELECT
    *,
    STDDEV_SAMP(zone_flow) OVER (
      PARTITION BY equipment_id ORDER BY timestamp_utc
      ROWS BETWEEN 11 PRECEDING AND CURRENT ROW
    ) AS roll_std,
    AVG(zone_flow) OVER (
      PARTITION BY equipment_id ORDER BY timestamp_utc
      ROWS BETWEEN 11 PRECEDING AND CURRENT ROW
    ) AS roll_mean,
    COUNT(zone_flow) OVER (
      PARTITION BY equipment_id ORDER BY timestamp_utc
      ROWS BETWEEN 11 PRECEDING AND CURRENT ROW
    ) AS roll_n
  FROM h
),
base AS (
  SELECT
    equipment_id,
    timestamp_utc,
    CAST(CASE
      WHEN COALESCE(fan_on, 0) = 0 THEN 0
      WHEN zone_flow IS NULL THEN 0
      WHEN min_flow_sp IS NOT NULL AND zone_flow > 25 AND zone_flow < min_flow_sp THEN 1
      WHEN roll_n >= 6
           AND zone_flow IS NOT NULL
           AND roll_std < 15
           AND roll_mean > 200 THEN 1
      WHEN min_flow_sp IS NOT NULL
           AND roll_n >= 6
           AND min_flow_sp > 250
           AND roll_std < 15 THEN 1
      ELSE 0
    END AS INT) AS raw_fault
  FROM rolled
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
    CASE WHEN raw_fault = 1 AND streak_len >= 3 THEN 1 ELSE 0 END AS confirmed
  FROM ranked
)
SELECT
  equipment_id,
  SUM(confirmed) * 300 / 3600.0 AS fault_hours
FROM final
GROUP BY equipment_id;

EXECUTE fdd_rule_49;
DEALLOCATE fdd_rule_49;

-- RESET-1
PREPARE fdd_rule_50 AS
-- PostgreSQL adaptation. Render numeric template parameters with render_rule.py.
-- Inputs must be scoped to one tenant/site and cadence; see README.md.
-- reset1_sat_oa_reset.sql — SAT SP not tracking OA reset curve
-- expected = RESET_SAT_AT_65 + RESET_SLOPE * (oa_t - RESET_OAT_REF)
WITH h AS (
  SELECT
    equipment_id,
    timestamp_utc,
    sat_sp,
    oa_t,
    CASE
      WHEN fan_status IS NOT NULL THEN CASE WHEN fan_status > 0.05 THEN 1 ELSE 0 END
      WHEN fan_cmd IS NOT NULL THEN CASE WHEN (CASE WHEN fan_cmd > 1.0 THEN fan_cmd / 100.0 ELSE fan_cmd END) > 0.05 THEN 1 ELSE 0 END
      ELSE 1
    END AS fan_on
  FROM history
),
base AS (
  SELECT
    equipment_id,
    timestamp_utc,
    CAST(CASE
      WHEN COALESCE(fan_on, 0) = 0 THEN 0
      WHEN sat_sp IS NULL OR oa_t IS NULL THEN 0
      WHEN abs(sat_sp - (52 + 0.25 * (oa_t - 65))) > 3 THEN 1
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
    CASE WHEN raw_fault = 1 AND streak_len >= 3 THEN 1 ELSE 0 END AS confirmed
  FROM ranked
)
SELECT
  equipment_id,
  SUM(confirmed) * 300 / 3600.0 AS fault_hours
FROM final
GROUP BY equipment_id;

EXECUTE fdd_rule_50;
DEALLOCATE fdd_rule_50;

-- CHW-NOLOAD-1
PREPARE fdd_rule_51 AS
-- PostgreSQL adaptation. Render numeric template parameters with render_rule.py.
-- Inputs must be scoped to one tenant/site and cadence; see README.md.
-- chw_noload_1.sql — Chiller running with no building load
-- When both zone and AHU load-satisfied flags are null, emit
-- SKIPPED_MISSING_ROLES (do not PASS 0 h). Prefer load_satisfaction
-- enrichment pandas uses when those columns are mapped.
WITH h AS (
  SELECT
    equipment_id,
    timestamp_utc,
    chiller_status,
    chiller_cmd,
    chw_pump_status,
    CASE WHEN chw_pump_cmd IS NULL THEN NULL WHEN chw_pump_cmd > 1.0 THEN chw_pump_cmd / 100.0 ELSE chw_pump_cmd END AS pump_cmd,
    building_zone_load_satisfied,
    building_ahu_load_satisfied,
    CASE
      WHEN building_zone_load_satisfied IS NOT NULL
        OR building_ahu_load_satisfied IS NOT NULL THEN 1
      ELSE 0
    END AS sat_present,
    COALESCE(building_zone_load_satisfied, building_ahu_load_satisfied) AS load_sat
  FROM history
),
proof AS (
  SELECT
    equipment_id,
    timestamp_utc,
    sat_present,
    load_sat,
    CASE
      WHEN chiller_status IS NULL AND chiller_cmd IS NULL
           AND chw_pump_status IS NULL AND pump_cmd IS NULL THEN NULL
      WHEN COALESCE(chiller_status, 0) > 0.05 THEN 1
      WHEN COALESCE(chiller_cmd, 0) > 0.05 THEN 1
      WHEN COALESCE(chw_pump_status, 0) > 0.05 THEN 1
      WHEN COALESCE(pump_cmd, 0) > 0.05 THEN 1
      ELSE 0
    END AS running
  FROM h
),
base AS (
  SELECT
    equipment_id,
    timestamp_utc,
    sat_present,
    CAST(CASE
      WHEN sat_present = 0 THEN 0
      WHEN running IS NULL OR load_sat IS NULL THEN 0
      WHEN running = 1 AND load_sat > 0.5 THEN 1
      ELSE 0
    END AS INT) AS raw_fault
  FROM proof
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
    sat_present,
    CASE WHEN raw_fault = 1 AND streak_len >= 6 THEN 1 ELSE 0 END AS confirmed
  FROM ranked
)
SELECT
  equipment_id,
  SUM(confirmed) * 300 / 3600.0 AS fault_hours,
  CASE
    WHEN MAX(sat_present) = 0 THEN 'SKIPPED_MISSING_ROLES'
    WHEN SUM(confirmed) > 0 THEN 'FAULT'
    ELSE 'PASS'
  END AS status
FROM final
GROUP BY equipment_id;

EXECUTE fdd_rule_51;
DEALLOCATE fdd_rule_51;

-- CHW-1
PREPARE fdd_rule_52 AS
-- PostgreSQL adaptation. Render numeric template parameters with render_rule.py.
-- Inputs must be scoped to one tenant/site and cadence; see README.md.
-- chw1_low_dt.sql — Low chilled-water ΔT
-- Operational proof required: status / current / power / flow / pump cmd.
-- Missing proof → 0 fault hours (pandas twin returns SKIPPED_MISSING_ROLES).
-- Proven off (zeros) → 0 fault hours.
WITH h AS (
  SELECT
    equipment_id,
    timestamp_utc,
    chw_supply_t, chw_return_t,
    CASE WHEN chw_pump_cmd IS NULL THEN NULL WHEN chw_pump_cmd > 1.0 THEN chw_pump_cmd / 100.0 ELSE chw_pump_cmd END AS pump,
    chiller_status,
    chiller_current,
    chiller_amps,
    chiller_power,
    chw_flow,
    pump_status
  FROM history
),
proof AS (
  SELECT
    *,
    CASE
      WHEN pump_status IS NOT NULL THEN CASE WHEN pump_status > 0.05 THEN 1 ELSE 0 END
      WHEN chiller_status IS NOT NULL THEN CASE WHEN chiller_status > 0.05 THEN 1 ELSE 0 END
      WHEN chiller_current IS NOT NULL THEN CASE WHEN chiller_current > 0.5 THEN 1 ELSE 0 END
      WHEN chiller_amps IS NOT NULL THEN CASE WHEN chiller_amps > 0.5 THEN 1 ELSE 0 END
      WHEN chiller_power IS NOT NULL THEN CASE WHEN chiller_power > 0.5 THEN 1 ELSE 0 END
      WHEN chw_flow IS NOT NULL THEN CASE WHEN chw_flow > 1.0 THEN 1 ELSE 0 END
      WHEN pump IS NOT NULL THEN CASE WHEN pump > 0.05 THEN 1 ELSE 0 END
      ELSE NULL
    END AS proof_on
  FROM h
),
base AS (
  SELECT
    equipment_id,
    timestamp_utc,
    CAST(CASE
      WHEN chw_supply_t IS NULL OR chw_return_t IS NULL THEN 0
      WHEN proof_on IS NULL THEN 0
      WHEN proof_on = 0 THEN 0
      WHEN (chw_return_t - chw_supply_t) < 4 THEN 1
      ELSE 0
    END AS INT) AS raw_fault
  FROM proof
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
    CASE WHEN raw_fault = 1 AND streak_len >= 3 THEN 1 ELSE 0 END AS confirmed
  FROM ranked
)
SELECT
  equipment_id,
  SUM(confirmed) * 300 / 3600.0 AS fault_hours
FROM final
GROUP BY equipment_id;

EXECUTE fdd_rule_52;
DEALLOCATE fdd_rule_52;

-- CHW-2
PREPARE fdd_rule_53 AS
-- PostgreSQL adaptation. Render numeric template parameters with render_rule.py.
-- Inputs must be scoped to one tenant/site and cadence; see README.md.
-- chw2_dp_low.sql — DP below SP at max pump speed
WITH h AS (
  SELECT
    equipment_id,
    timestamp_utc,
    chw_dp, chw_dp_sp,
    CASE WHEN chw_pump_cmd IS NULL THEN NULL WHEN chw_pump_cmd > 1.0 THEN chw_pump_cmd / 100.0 ELSE chw_pump_cmd END AS pump,
    pump_status, chiller_status, chw_flow
  FROM history
),
proof AS (
  SELECT
    *,
    CASE
      WHEN pump_status IS NOT NULL THEN CASE WHEN pump_status > 0.05 THEN 1 ELSE 0 END
      WHEN chiller_status IS NOT NULL THEN CASE WHEN chiller_status > 0.05 THEN 1 ELSE 0 END
      WHEN chw_flow IS NOT NULL THEN CASE WHEN chw_flow > 1.0 THEN 1 ELSE 0 END
      WHEN pump IS NOT NULL THEN CASE WHEN pump > 0.05 THEN 1 ELSE 0 END
      ELSE NULL
    END AS proof_on
  FROM h
),
base AS (
  SELECT
    equipment_id,
    timestamp_utc,
    CAST(CASE
      WHEN proof_on IS NULL OR proof_on = 0 THEN 0
      WHEN chw_dp IS NULL OR chw_dp_sp IS NULL OR pump IS NULL THEN 0
      WHEN pump >= 0.87 AND chw_dp < chw_dp_sp - 2.2 THEN 1
      ELSE 0
    END AS INT) AS raw_fault
  FROM proof
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
    CASE WHEN raw_fault = 1 AND streak_len >= 1 THEN 1 ELSE 0 END AS confirmed
  FROM ranked
)
SELECT
  equipment_id,
  SUM(confirmed) * 300 / 3600.0 AS fault_hours
FROM final
GROUP BY equipment_id;

EXECUTE fdd_rule_53;
DEALLOCATE fdd_rule_53;

-- CHW-3
PREPARE fdd_rule_54 AS
-- PostgreSQL adaptation. Render numeric template parameters with render_rule.py.
-- Inputs must be scoped to one tenant/site and cadence; see README.md.
-- chw3_supply_band.sql — Plant supply temp outside deadband
WITH h AS (
  SELECT
    equipment_id,
    timestamp_utc,
    chw_supply_t, chw_supply_sp,
    CASE WHEN chw_pump_cmd IS NULL THEN NULL WHEN chw_pump_cmd > 1.0 THEN chw_pump_cmd / 100.0 ELSE chw_pump_cmd END AS pump,
    pump_status, chiller_status, chw_flow
  FROM history
),
proof AS (
  SELECT *,
    CASE
      WHEN pump_status IS NOT NULL THEN CASE WHEN pump_status > 0.05 THEN 1 ELSE 0 END
      WHEN chiller_status IS NOT NULL THEN CASE WHEN chiller_status > 0.05 THEN 1 ELSE 0 END
      WHEN chw_flow IS NOT NULL THEN CASE WHEN chw_flow > 1.0 THEN 1 ELSE 0 END
      WHEN pump IS NOT NULL THEN CASE WHEN pump > 0.05 THEN 1 ELSE 0 END
      ELSE NULL
    END AS proof_on
  FROM h
),
base AS (
  SELECT
    equipment_id,
    timestamp_utc,
    CAST(CASE
      WHEN proof_on IS NULL OR proof_on = 0 THEN 0
      WHEN chw_supply_t IS NULL OR chw_supply_sp IS NULL THEN 0
      WHEN ABS(chw_supply_t - chw_supply_sp) > 2.2 THEN 1
      ELSE 0
    END AS INT) AS raw_fault
  FROM proof
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
    CASE WHEN raw_fault = 1 AND streak_len >= 1 THEN 1 ELSE 0 END AS confirmed
  FROM ranked
)
SELECT
  equipment_id,
  SUM(confirmed) * 300 / 3600.0 AS fault_hours
FROM final
GROUP BY equipment_id;

EXECUTE fdd_rule_54;
DEALLOCATE fdd_rule_54;

-- CHW-4
PREPARE fdd_rule_55 AS
-- PostgreSQL adaptation. Render numeric template parameters with render_rule.py.
-- Inputs must be scoped to one tenant/site and cadence; see README.md.
-- chw4_flow_high.sql — Flow high at max pump
WITH h AS (
  SELECT
    equipment_id,
    timestamp_utc,
    chw_flow,
    CASE WHEN chw_pump_cmd IS NULL THEN NULL WHEN chw_pump_cmd > 1.0 THEN chw_pump_cmd / 100.0 ELSE chw_pump_cmd END AS pump,
    pump_status, chiller_status
  FROM history
),
proof AS (
  SELECT *,
    CASE
      WHEN pump_status IS NOT NULL THEN CASE WHEN pump_status > 0.05 THEN 1 ELSE 0 END
      WHEN chiller_status IS NOT NULL THEN CASE WHEN chiller_status > 0.05 THEN 1 ELSE 0 END
      WHEN pump IS NOT NULL THEN CASE WHEN pump > 0.05 THEN 1 ELSE 0 END
      ELSE NULL
    END AS proof_on
  FROM h
),
base AS (
  SELECT
    equipment_id,
    timestamp_utc,
    CAST(CASE
      WHEN proof_on IS NULL OR proof_on = 0 THEN 0
      WHEN chw_flow IS NULL OR pump IS NULL THEN 0
      WHEN pump >= 0.87 AND chw_flow > 1100 THEN 1
      ELSE 0
    END AS INT) AS raw_fault
  FROM proof
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
    CASE WHEN raw_fault = 1 AND streak_len >= 1 THEN 1 ELSE 0 END AS confirmed
  FROM ranked
)
SELECT
  equipment_id,
  SUM(confirmed) * 300 / 3600.0 AS fault_hours
FROM final
GROUP BY equipment_id;

EXECUTE fdd_rule_55;
DEALLOCATE fdd_rule_55;

-- CW-OPT-1
PREPARE fdd_rule_56 AS
-- PostgreSQL adaptation. Render numeric template parameters with render_rule.py.
-- Inputs must be scoped to one tenant/site and cadence; see README.md.
-- cw_opt_1.sql — Condenser water not optimized vs wet-bulb
WITH h AS (
  SELECT
    equipment_id,
    timestamp_utc,
    cw_supply_t,
    web_wb_t,
    pump_status,
    chiller_status,
    chw_flow,
    chw_pump_cmd,
    CASE
      WHEN pump_status IS NOT NULL THEN CASE WHEN pump_status > 0.05 THEN 1 ELSE 0 END
      WHEN chiller_status IS NOT NULL THEN CASE WHEN chiller_status > 0.05 THEN 1 ELSE 0 END
      WHEN chw_flow IS NOT NULL THEN CASE WHEN chw_flow > 1.0 THEN 1 ELSE 0 END
      WHEN chw_pump_cmd IS NOT NULL THEN CASE WHEN (CASE WHEN chw_pump_cmd > 1.0 THEN chw_pump_cmd / 100.0 ELSE chw_pump_cmd END) > 0.05 THEN 1 ELSE 0 END
      ELSE 0
    END AS proof_on
  FROM history
),
base AS (
  SELECT
    equipment_id,
    timestamp_utc,
    CAST(CASE
      WHEN COALESCE(proof_on, 0) = 0 THEN 0
      WHEN cw_supply_t IS NULL OR web_wb_t IS NULL THEN 0
      WHEN cw_supply_t < web_wb_t + 7 - 2 THEN 1
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
    CASE WHEN raw_fault = 1 AND streak_len >= 3 THEN 1 ELSE 0 END AS confirmed
  FROM ranked
)
SELECT
  equipment_id,
  SUM(confirmed) * 300 / 3600.0 AS fault_hours
FROM final
GROUP BY equipment_id;

EXECUTE fdd_rule_56;
DEALLOCATE fdd_rule_56;

-- CW-APR-1
PREPARE fdd_rule_57 AS
-- PostgreSQL adaptation. Render numeric template parameters with render_rule.py.
-- Inputs must be scoped to one tenant/site and cadence; see README.md.
-- cw_apr_1.sql — High CW approach at full tower fan
WITH h AS (
  SELECT
    equipment_id,
    timestamp_utc,
    cw_supply_t, web_wb_t,
    CASE WHEN tower_fan_cmd IS NULL THEN NULL WHEN tower_fan_cmd > 1.0 THEN tower_fan_cmd / 100.0 ELSE tower_fan_cmd END AS fan,
    pump_status,
    chiller_status,
    chw_flow,
    chw_pump_cmd,
    CASE
      WHEN pump_status IS NOT NULL THEN CASE WHEN pump_status > 0.05 THEN 1 ELSE 0 END
      WHEN chiller_status IS NOT NULL THEN CASE WHEN chiller_status > 0.05 THEN 1 ELSE 0 END
      WHEN chw_flow IS NOT NULL THEN CASE WHEN chw_flow > 1.0 THEN 1 ELSE 0 END
      WHEN chw_pump_cmd IS NOT NULL THEN CASE WHEN (CASE WHEN chw_pump_cmd > 1.0 THEN chw_pump_cmd / 100.0 ELSE chw_pump_cmd END) > 0.05 THEN 1 ELSE 0 END
      ELSE 0
    END AS proof_on

  FROM history
),
base AS (
  SELECT
    equipment_id,
    timestamp_utc,
    CAST(CASE
      WHEN COALESCE(proof_on, 0) = 0 THEN 0
      WHEN cw_supply_t IS NULL OR web_wb_t IS NULL OR fan IS NULL THEN 0
      WHEN fan >= 0.95
       AND (cw_supply_t - web_wb_t) > 8 THEN 1
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
    CASE WHEN raw_fault = 1 AND streak_len >= 3 THEN 1 ELSE 0 END AS confirmed
  FROM ranked
)
SELECT
  equipment_id,
  SUM(confirmed) * 300 / 3600.0 AS fault_hours
FROM final
GROUP BY equipment_id;

EXECUTE fdd_rule_57;
DEALLOCATE fdd_rule_57;

-- CW-FAN-1
PREPARE fdd_rule_58 AS
-- PostgreSQL adaptation. Render numeric template parameters with render_rule.py.
-- Inputs must be scoped to one tenant/site and cadence; see README.md.
-- cw_fan_1.sql — Excess tower fan energy vs wet-bulb limit
WITH h AS (
  SELECT
    equipment_id,
    timestamp_utc,
    cw_supply_t, web_wb_t,
    CASE WHEN tower_fan_cmd IS NULL THEN NULL WHEN tower_fan_cmd > 1.0 THEN tower_fan_cmd / 100.0 ELSE tower_fan_cmd END AS fan,
    pump_status,
    chiller_status,
    chw_flow,
    chw_pump_cmd,
    CASE
      WHEN pump_status IS NOT NULL THEN CASE WHEN pump_status > 0.05 THEN 1 ELSE 0 END
      WHEN chiller_status IS NOT NULL THEN CASE WHEN chiller_status > 0.05 THEN 1 ELSE 0 END
      WHEN chw_flow IS NOT NULL THEN CASE WHEN chw_flow > 1.0 THEN 1 ELSE 0 END
      WHEN chw_pump_cmd IS NOT NULL THEN CASE WHEN (CASE WHEN chw_pump_cmd > 1.0 THEN chw_pump_cmd / 100.0 ELSE chw_pump_cmd END) > 0.05 THEN 1 ELSE 0 END
      ELSE 0
    END AS proof_on

  FROM history
),
base AS (
  SELECT
    equipment_id,
    timestamp_utc,
    CAST(CASE
      WHEN COALESCE(proof_on, 0) = 0 THEN 0
      WHEN cw_supply_t IS NULL OR web_wb_t IS NULL OR fan IS NULL THEN 0
      WHEN fan >= 0.95
       AND cw_supply_t > web_wb_t + 7 + 5 THEN 1
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
    CASE WHEN raw_fault = 1 AND streak_len >= 3 THEN 1 ELSE 0 END AS confirmed
  FROM ranked
)
SELECT
  equipment_id,
  SUM(confirmed) * 300 / 3600.0 AS fault_hours
FROM final
GROUP BY equipment_id;

EXECUTE fdd_rule_58;
DEALLOCATE fdd_rule_58;

-- HP-1
PREPARE fdd_rule_59 AS
-- PostgreSQL adaptation. Render numeric template parameters with render_rule.py.
-- Inputs must be scoped to one tenant/site and cadence; see README.md.
-- hp1_discharge_cold.sql — Discharge cold when heating
WITH h AS (
  SELECT
    equipment_id,
    timestamp_utc,
    sat, zone_t,
    CASE WHEN fan_cmd IS NULL THEN NULL WHEN fan_cmd > 1.0 THEN fan_cmd / 100.0 ELSE fan_cmd END AS fan,
    compressor_status,
    fan_status,
    CASE
      WHEN compressor_status IS NOT NULL THEN CASE WHEN compressor_status > 0.05 THEN 1 ELSE 0 END
      WHEN fan_status IS NOT NULL THEN CASE WHEN fan_status > 0.05 THEN 1 ELSE 0 END
      WHEN fan_cmd IS NOT NULL THEN CASE WHEN (CASE WHEN fan_cmd > 1.0 THEN fan_cmd / 100.0 ELSE fan_cmd END) > 0.05 THEN 1 ELSE 0 END
      ELSE 1
    END AS proof_on

  FROM history
),
base AS (
  SELECT
    equipment_id,
    timestamp_utc,
    CAST(CASE
      WHEN COALESCE(proof_on, 0) = 0 THEN 0
      WHEN sat IS NULL OR zone_t IS NULL OR fan IS NULL THEN 0
      WHEN fan >= 0.05 AND zone_t < 69 AND sat < 85 THEN 1
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
    CASE WHEN raw_fault = 1 AND streak_len >= 2 THEN 1 ELSE 0 END AS confirmed
  FROM ranked
)
SELECT
  equipment_id,
  SUM(confirmed) * 300 / 3600.0 AS fault_hours
FROM final
GROUP BY equipment_id;

EXECUTE fdd_rule_59;
DEALLOCATE fdd_rule_59;

-- WX-1
PREPARE fdd_rule_60 AS
-- PostgreSQL adaptation. Render numeric template parameters with render_rule.py.
-- Inputs must be scoped to one tenant/site and cadence; see README.md.
-- wx1_oa_spike.sql — OA temperature spike
WITH h AS (
  SELECT
    equipment_id,
    timestamp_utc,
    oa_t,
    LAG(oa_t) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc) AS prev_oa_t
  FROM history
),
base AS (
  SELECT
    equipment_id,
    timestamp_utc,
    CAST(CASE
      WHEN oa_t IS NULL OR prev_oa_t IS NULL THEN 0
      WHEN ABS(oa_t - prev_oa_t) > 16 THEN 1
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
    CASE WHEN raw_fault = 1 AND streak_len >= 1 THEN 1 ELSE 0 END AS confirmed
  FROM ranked
)
SELECT
  equipment_id,
  SUM(confirmed) * 300 / 3600.0 AS fault_hours
FROM final
GROUP BY equipment_id;

EXECUTE fdd_rule_60;
DEALLOCATE fdd_rule_60;

-- TRIM-1
PREPARE fdd_rule_61 AS
-- PostgreSQL adaptation. Render numeric template parameters with render_rule.py.
-- Inputs must be scoped to one tenant/site and cadence; see README.md.
-- trim1_duct_static.sql — Duct static trim advisory
-- Pandas trim1: high actual duct static + low VAV pressure-request sum.
-- Prefer duct_static (measured); fall back to duct_static_sp when only SP is mapped.
WITH base AS (
  SELECT
    equipment_id,
    timestamp_utc,
    CAST(CASE
      WHEN COALESCE(duct_static, duct_static_sp) IS NULL THEN 0
      WHEN COALESCE(duct_static, duct_static_sp) > 1.35
       AND COALESCE(static_reset_request, 0) <= 1 THEN 1
      ELSE 0
    END AS INT) AS raw_fault,
    fan_cmd,
    fan_status,
    CASE
      WHEN fan_status IS NOT NULL THEN CASE WHEN fan_status > 0.05 THEN 1 ELSE 0 END
      WHEN fan_cmd IS NOT NULL THEN CASE WHEN (CASE WHEN fan_cmd > 1.0 THEN fan_cmd / 100.0 ELSE fan_cmd END) > 0.01 THEN 1 ELSE 0 END
      ELSE 1
    END AS fan_on

  FROM history
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
    CASE WHEN raw_fault = 1 AND streak_len >= 6 THEN 1 ELSE 0 END AS confirmed
  FROM ranked
)
SELECT
  equipment_id,
  SUM(confirmed) * 300 / 3600.0 AS fault_hours
FROM final
GROUP BY equipment_id;

EXECUTE fdd_rule_61;
DEALLOCATE fdd_rule_61;

-- TRIM-3
PREPARE fdd_rule_62 AS
-- PostgreSQL adaptation. Render numeric template parameters with render_rule.py.
-- Inputs must be scoped to one tenant/site and cadence; see README.md.
-- trim3_hwst.sql — HWST trim advisory
WITH h AS (
  SELECT
    equipment_id,
    timestamp_utc,
    hw_supply_t,
    hw_reset_request_sum,
    pump_status,
    chiller_status,
    chw_flow,
    chw_pump_cmd,
    CASE
      WHEN pump_status IS NOT NULL THEN CASE WHEN pump_status > 0.05 THEN 1 ELSE 0 END
      WHEN chiller_status IS NOT NULL THEN CASE WHEN chiller_status > 0.05 THEN 1 ELSE 0 END
      WHEN chw_flow IS NOT NULL THEN CASE WHEN chw_flow > 1.0 THEN 1 ELSE 0 END
      WHEN chw_pump_cmd IS NOT NULL THEN CASE WHEN (CASE WHEN chw_pump_cmd > 1.0 THEN chw_pump_cmd / 100.0 ELSE chw_pump_cmd END) > 0.05 THEN 1 ELSE 0 END
      ELSE 0
    END AS proof_on
  FROM history
),
base AS (
  SELECT
    equipment_id,
    timestamp_utc,
    CAST(CASE
      WHEN COALESCE(proof_on, 0) = 0 THEN 0
      WHEN hw_supply_t IS NULL THEN 0
      WHEN hw_supply_t > 160
       AND COALESCE(hw_reset_request_sum, 0) <= 1 THEN 1
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
    CASE WHEN raw_fault = 1 AND streak_len >= 6 THEN 1 ELSE 0 END AS confirmed
  FROM ranked
)
SELECT
  equipment_id,
  SUM(confirmed) * 300 / 3600.0 AS fault_hours
FROM final
GROUP BY equipment_id;

EXECUTE fdd_rule_62;
DEALLOCATE fdd_rule_62;

-- TRIM-4
PREPARE fdd_rule_63 AS
-- PostgreSQL adaptation. Render numeric template parameters with render_rule.py.
-- Inputs must be scoped to one tenant/site and cadence; see README.md.
-- trim4_chw_reset.sql — CHW plant reset advisory
WITH h AS (
  SELECT
    equipment_id,
    timestamp_utc,
    chw_supply_t,
    chw_reset_request_sum,
    pump_status,
    chiller_status,
    chw_flow,
    chw_pump_cmd,
    CASE
      WHEN pump_status IS NOT NULL THEN CASE WHEN pump_status > 0.05 THEN 1 ELSE 0 END
      WHEN chiller_status IS NOT NULL THEN CASE WHEN chiller_status > 0.05 THEN 1 ELSE 0 END
      WHEN chw_flow IS NOT NULL THEN CASE WHEN chw_flow > 1.0 THEN 1 ELSE 0 END
      WHEN chw_pump_cmd IS NOT NULL THEN CASE WHEN (CASE WHEN chw_pump_cmd > 1.0 THEN chw_pump_cmd / 100.0 ELSE chw_pump_cmd END) > 0.05 THEN 1 ELSE 0 END
      ELSE 0
    END AS proof_on
  FROM history
),
base AS (
  SELECT
    equipment_id,
    timestamp_utc,
    CAST(CASE
      WHEN COALESCE(proof_on, 0) = 0 THEN 0
      WHEN chw_supply_t IS NULL THEN 0
      WHEN chw_supply_t < 45
       AND COALESCE(chw_reset_request_sum, 0) <= 1 THEN 1
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
    CASE WHEN raw_fault = 1 AND streak_len >= 6 THEN 1 ELSE 0 END AS confirmed
  FROM ranked
)
SELECT
  equipment_id,
  SUM(confirmed) * 300 / 3600.0 AS fault_hours
FROM final
GROUP BY equipment_id;

EXECUTE fdd_rule_63;
DEALLOCATE fdd_rule_63;

-- SCHED-1
PREPARE fdd_rule_64 AS
-- PostgreSQL adaptation. Render numeric template parameters with render_rule.py.
-- Inputs must be scoped to one tenant/site and cadence; see README.md.
-- sched1_unoccupied_runtime.sql — Excess / wasted unoccupied runtime
-- Pandas sched1: unoccupied & fan_on; when zone_t mapped, also require comfort band
-- (zone already satisfied → optimal-start / bad schedule signal).
-- When zone_t is absent from history, the runner injects NULL zone_t (optional role)
-- so behavior matches pandas “no zone → base only”.
-- Portable occupancy: literal 'unoccupied' OR numeric/boolean falsey (0 / 0.0 / false).
WITH base AS (
  SELECT
    equipment_id,
    timestamp_utc,
        CAST(CASE
          WHEN occ_mode IS NULL OR fan_status IS NULL THEN 0
          WHEN fan_status > 0.5
            AND (
              LOWER(trim(CAST(occ_mode AS VARCHAR))) IN
                ('unoccupied','unocc','off','false','night','standby','setback','no')
              OR (
                fdd.try_double(trim(CAST(occ_mode AS VARCHAR))) IS NOT NULL
                AND fdd.try_double(trim(CAST(occ_mode AS VARCHAR))) <= 0.05
              )
            )
            AND (
              zone_t IS NULL
              OR (zone_t >= 70 AND zone_t <= 75)
            )
          THEN 1
          ELSE 0
        END AS INT) AS raw_fault
  FROM history
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
    CASE WHEN raw_fault = 1 AND streak_len >= 6 THEN 1 ELSE 0 END AS confirmed
  FROM ranked
)
SELECT
  equipment_id,
  SUM(confirmed) * 300 / 3600.0 AS fault_hours
FROM final
GROUP BY equipment_id;

EXECUTE fdd_rule_64;
DEALLOCATE fdd_rule_64;

-- SCHED-247
PREPARE fdd_rule_65 AS
-- PostgreSQL adaptation. Render numeric template parameters with render_rule.py.
-- Inputs must be scoped to one tenant/site and cadence; see README.md.
-- sched247_always_on.sql — Always-on fan or pump runtime
-- Pandas `_sched247`: ranked proof (status > command), then FAULT only when
-- mean(on) >= always_on_pct over the whole analysis window. Confirmed hours
-- are the on-mask after that gate (not a streak-only screen).
-- Pressure is not used for the FAULT mask (4.3 migration).
WITH h AS (
  SELECT
    equipment_id,
    timestamp_utc,
    fan_status,
    pump_status,
    chiller_status,
    CASE WHEN fan_cmd IS NULL THEN NULL WHEN fan_cmd > 1.0 THEN fan_cmd / 100.0 ELSE fan_cmd END AS fan
  FROM history
),
proof AS (
  SELECT
    equipment_id,
    timestamp_utc,
    CAST(CASE
      WHEN fan_status IS NOT NULL THEN CASE WHEN fan_status > 0.05 THEN 1 ELSE 0 END
      WHEN pump_status IS NOT NULL THEN CASE WHEN pump_status > 0.05 THEN 1 ELSE 0 END
      WHEN chiller_status IS NOT NULL THEN CASE WHEN chiller_status > 0.05 THEN 1 ELSE 0 END
      WHEN fan IS NOT NULL THEN CASE WHEN fan >= 0.05 THEN 1 ELSE 0 END
      ELSE 0
    END AS INT) AS on_bit
  FROM h
),
win AS (
  SELECT
    equipment_id,
    timestamp_utc,
    on_bit,
    AVG(CAST(on_bit AS DOUBLE PRECISION)) OVER (PARTITION BY equipment_id) AS on_frac
  FROM proof
),
base AS (
  SELECT
    equipment_id,
    timestamp_utc,
    CAST(CASE
      WHEN on_frac >= 0.95 AND on_bit = 1 THEN 1
      ELSE 0
    END AS INT) AS raw_fault
  FROM win
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
    CASE WHEN raw_fault = 1 AND streak_len >= 12 THEN 1 ELSE 0 END AS confirmed
  FROM ranked
)
SELECT
  equipment_id,
  SUM(confirmed) * 300 / 3600.0 AS fault_hours
FROM final
GROUP BY equipment_id;

EXECUTE fdd_rule_65;
DEALLOCATE fdd_rule_65;

-- FCU-SENSOR-NULL
PREPARE fdd_rule_66 AS
-- PostgreSQL adaptation. Render numeric template parameters with render_rule.py.
-- Inputs must be scoped to one tenant/site and cadence; see README.md.
-- FCU-SENSOR-NULL — own zone setpoint exists while a mapped zone sensor is predominantly null.
-- The runner rewrites this file to zero hours when zone_t is absent from history.
WITH coverage AS (
  SELECT equipment_id,
    SUM(CASE WHEN zone_air_temp_sp IS NOT NULL THEN 1 ELSE 0 END) AS eligible_rows,
    SUM(CASE WHEN zone_air_temp_sp IS NOT NULL AND zone_t IS NULL THEN 1 ELSE 0 END) AS null_rows
  FROM history
  GROUP BY equipment_id
)
SELECT equipment_id,
  CASE WHEN eligible_rows > 0 AND CAST(null_rows AS DOUBLE PRECISION) / eligible_rows >= 0.9
    THEN null_rows * 300 / 3600.0 ELSE 0.0 END AS fault_hours
FROM coverage;

EXECUTE fdd_rule_66;
DEALLOCATE fdd_rule_66;

-- FCU-HTG-COIL
PREPARE fdd_rule_67 AS
-- PostgreSQL adaptation. Render numeric template parameters with render_rule.py.
-- Inputs must be scoped to one tenant/site and cadence; see README.md.
-- fcu_htg_coil.sql — first-class FCU screening rule
WITH normalized AS (
  SELECT equipment_id, timestamp_utc, sat, zone_t, zone_co2,
    CASE WHEN htg_valve_pct IS NULL THEN NULL WHEN htg_valve_pct > 1.0 THEN htg_valve_pct / 100.0 ELSE htg_valve_pct END AS htg,
    CASE WHEN clg_valve_pct IS NULL THEN NULL WHEN clg_valve_pct > 1.0 THEN clg_valve_pct / 100.0 ELSE clg_valve_pct END AS clg,
    CASE WHEN damper_cmd IS NULL THEN NULL WHEN damper_cmd > 1.0 THEN damper_cmd / 100.0 ELSE damper_cmd END AS dcmd,
    CASE WHEN damper_pct IS NULL THEN NULL WHEN damper_pct > 1.0 THEN damper_pct / 100.0 ELSE damper_pct END AS dpos,
    CASE
      WHEN fan_status IS NOT NULL THEN CASE WHEN fan_status > 0.05 THEN 1 ELSE 0 END
      WHEN fan_cmd IS NOT NULL THEN CASE WHEN (CASE WHEN fan_cmd > 1.0 THEN fan_cmd / 100.0 ELSE fan_cmd END) > 0.10 THEN 1 ELSE 0 END
      ELSE 0
    END AS fan_on
  FROM history
), base AS (
  SELECT equipment_id, timestamp_utc,
    CAST(CASE WHEN sat IS NOT NULL AND zone_t IS NOT NULL AND fan_on = 1 AND htg >= 0.8 AND sat - zone_t < 5.4 THEN 1 ELSE 0 END AS INT) AS raw_fault
  FROM normalized
), lagged AS (
  SELECT *, CASE WHEN raw_fault = LAG(raw_fault) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc) THEN 0 ELSE 1 END AS is_new_streak
  FROM base
), grouped AS (
  SELECT *, SUM(is_new_streak) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS UNBOUNDED PRECEDING) AS streak_id
  FROM lagged
), ranked AS (
  SELECT *, ROW_NUMBER() OVER (PARTITION BY equipment_id, streak_id ORDER BY timestamp_utc) AS streak_len
  FROM grouped
)
SELECT equipment_id,
  SUM(CASE WHEN raw_fault = 1 AND streak_len >= 3 THEN 1 ELSE 0 END) * 300 / 3600.0 AS fault_hours
FROM ranked
GROUP BY equipment_id;

EXECUTE fdd_rule_67;
DEALLOCATE fdd_rule_67;

-- FCU-CLG-COIL
PREPARE fdd_rule_68 AS
-- PostgreSQL adaptation. Render numeric template parameters with render_rule.py.
-- Inputs must be scoped to one tenant/site and cadence; see README.md.
-- fcu_clg_coil.sql — first-class FCU screening rule
WITH normalized AS (
  SELECT equipment_id, timestamp_utc, sat, zone_t, zone_co2,
    CASE WHEN htg_valve_pct IS NULL THEN NULL WHEN htg_valve_pct > 1.0 THEN htg_valve_pct / 100.0 ELSE htg_valve_pct END AS htg,
    CASE WHEN clg_valve_pct IS NULL THEN NULL WHEN clg_valve_pct > 1.0 THEN clg_valve_pct / 100.0 ELSE clg_valve_pct END AS clg,
    CASE WHEN damper_cmd IS NULL THEN NULL WHEN damper_cmd > 1.0 THEN damper_cmd / 100.0 ELSE damper_cmd END AS dcmd,
    CASE WHEN damper_pct IS NULL THEN NULL WHEN damper_pct > 1.0 THEN damper_pct / 100.0 ELSE damper_pct END AS dpos,
    CASE
      WHEN fan_status IS NOT NULL THEN CASE WHEN fan_status > 0.05 THEN 1 ELSE 0 END
      WHEN fan_cmd IS NOT NULL THEN CASE WHEN (CASE WHEN fan_cmd > 1.0 THEN fan_cmd / 100.0 ELSE fan_cmd END) > 0.10 THEN 1 ELSE 0 END
      ELSE 0
    END AS fan_on
  FROM history
), base AS (
  SELECT equipment_id, timestamp_utc,
    CAST(CASE WHEN sat IS NOT NULL AND zone_t IS NOT NULL AND fan_on = 1 AND clg >= 0.8 AND htg <= 0.05 AND sat - zone_t >= 0.0 THEN 1 ELSE 0 END AS INT) AS raw_fault
  FROM normalized
), lagged AS (
  SELECT *, CASE WHEN raw_fault = LAG(raw_fault) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc) THEN 0 ELSE 1 END AS is_new_streak
  FROM base
), grouped AS (
  SELECT *, SUM(is_new_streak) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS UNBOUNDED PRECEDING) AS streak_id
  FROM lagged
), ranked AS (
  SELECT *, ROW_NUMBER() OVER (PARTITION BY equipment_id, streak_id ORDER BY timestamp_utc) AS streak_len
  FROM grouped
)
SELECT equipment_id,
  SUM(CASE WHEN raw_fault = 1 AND streak_len >= 3 THEN 1 ELSE 0 END) * 300 / 3600.0 AS fault_hours
FROM ranked
GROUP BY equipment_id;

EXECUTE fdd_rule_68;
DEALLOCATE fdd_rule_68;

-- FCU-VALVE-PASS-HTG
PREPARE fdd_rule_69 AS
-- PostgreSQL adaptation. Render numeric template parameters with render_rule.py.
-- Inputs must be scoped to one tenant/site and cadence; see README.md.
-- fcu_valve_pass_htg.sql — first-class FCU screening rule
WITH normalized AS (
  SELECT equipment_id, timestamp_utc, sat, zone_t, zone_co2,
    CASE WHEN htg_valve_pct IS NULL THEN NULL WHEN htg_valve_pct > 1.0 THEN htg_valve_pct / 100.0 ELSE htg_valve_pct END AS htg,
    CASE WHEN clg_valve_pct IS NULL THEN NULL WHEN clg_valve_pct > 1.0 THEN clg_valve_pct / 100.0 ELSE clg_valve_pct END AS clg,
    CASE WHEN damper_cmd IS NULL THEN NULL WHEN damper_cmd > 1.0 THEN damper_cmd / 100.0 ELSE damper_cmd END AS dcmd,
    CASE WHEN damper_pct IS NULL THEN NULL WHEN damper_pct > 1.0 THEN damper_pct / 100.0 ELSE damper_pct END AS dpos,
    CASE
      WHEN fan_status IS NOT NULL THEN CASE WHEN fan_status > 0.05 THEN 1 ELSE 0 END
      WHEN fan_cmd IS NOT NULL THEN CASE WHEN (CASE WHEN fan_cmd > 1.0 THEN fan_cmd / 100.0 ELSE fan_cmd END) > 0.10 THEN 1 ELSE 0 END
      ELSE 0
    END AS fan_on
  FROM history
), base AS (
  SELECT equipment_id, timestamp_utc,
    CAST(CASE WHEN sat IS NOT NULL AND zone_t IS NOT NULL AND fan_on = 1 AND htg <= 0.05 AND clg <= 0.05 AND sat - zone_t > 5.4 THEN 1 ELSE 0 END AS INT) AS raw_fault
  FROM normalized
), lagged AS (
  SELECT *, CASE WHEN raw_fault = LAG(raw_fault) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc) THEN 0 ELSE 1 END AS is_new_streak
  FROM base
), grouped AS (
  SELECT *, SUM(is_new_streak) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS UNBOUNDED PRECEDING) AS streak_id
  FROM lagged
), ranked AS (
  SELECT *, ROW_NUMBER() OVER (PARTITION BY equipment_id, streak_id ORDER BY timestamp_utc) AS streak_len
  FROM grouped
)
SELECT equipment_id,
  SUM(CASE WHEN raw_fault = 1 AND streak_len >= 3 THEN 1 ELSE 0 END) * 300 / 3600.0 AS fault_hours
FROM ranked
GROUP BY equipment_id;

EXECUTE fdd_rule_69;
DEALLOCATE fdd_rule_69;

-- FCU-VALVE-PASS-CLG
PREPARE fdd_rule_70 AS
-- PostgreSQL adaptation. Render numeric template parameters with render_rule.py.
-- Inputs must be scoped to one tenant/site and cadence; see README.md.
-- fcu_valve_pass_clg.sql — first-class FCU screening rule
WITH normalized AS (
  SELECT equipment_id, timestamp_utc, sat, zone_t, zone_co2,
    CASE WHEN htg_valve_pct IS NULL THEN NULL WHEN htg_valve_pct > 1.0 THEN htg_valve_pct / 100.0 ELSE htg_valve_pct END AS htg,
    CASE WHEN clg_valve_pct IS NULL THEN NULL WHEN clg_valve_pct > 1.0 THEN clg_valve_pct / 100.0 ELSE clg_valve_pct END AS clg,
    CASE WHEN damper_cmd IS NULL THEN NULL WHEN damper_cmd > 1.0 THEN damper_cmd / 100.0 ELSE damper_cmd END AS dcmd,
    CASE WHEN damper_pct IS NULL THEN NULL WHEN damper_pct > 1.0 THEN damper_pct / 100.0 ELSE damper_pct END AS dpos,
    CASE
      WHEN fan_status IS NOT NULL THEN CASE WHEN fan_status > 0.05 THEN 1 ELSE 0 END
      WHEN fan_cmd IS NOT NULL THEN CASE WHEN (CASE WHEN fan_cmd > 1.0 THEN fan_cmd / 100.0 ELSE fan_cmd END) > 0.10 THEN 1 ELSE 0 END
      ELSE 0
    END AS fan_on
  FROM history
), base AS (
  SELECT equipment_id, timestamp_utc,
    CAST(CASE WHEN sat IS NOT NULL AND zone_t IS NOT NULL AND fan_on = 1 AND htg <= 0.05 AND clg <= 0.05 AND zone_t - sat > 5.4 THEN 1 ELSE 0 END AS INT) AS raw_fault
  FROM normalized
), lagged AS (
  SELECT *, CASE WHEN raw_fault = LAG(raw_fault) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc) THEN 0 ELSE 1 END AS is_new_streak
  FROM base
), grouped AS (
  SELECT *, SUM(is_new_streak) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS UNBOUNDED PRECEDING) AS streak_id
  FROM lagged
), ranked AS (
  SELECT *, ROW_NUMBER() OVER (PARTITION BY equipment_id, streak_id ORDER BY timestamp_utc) AS streak_len
  FROM grouped
)
SELECT equipment_id,
  SUM(CASE WHEN raw_fault = 1 AND streak_len >= 3 THEN 1 ELSE 0 END) * 300 / 3600.0 AS fault_hours
FROM ranked
GROUP BY equipment_id;

EXECUTE fdd_rule_70;
DEALLOCATE fdd_rule_70;

-- FCU-DAMPER-POS
PREPARE fdd_rule_71 AS
-- PostgreSQL adaptation. Render numeric template parameters with render_rule.py.
-- Inputs must be scoped to one tenant/site and cadence; see README.md.
-- fcu_damper_pos.sql — first-class FCU screening rule
WITH normalized AS (
  SELECT equipment_id, timestamp_utc, sat, zone_t, zone_co2,
    CASE WHEN htg_valve_pct IS NULL THEN NULL WHEN htg_valve_pct > 1.0 THEN htg_valve_pct / 100.0 ELSE htg_valve_pct END AS htg,
    CASE WHEN clg_valve_pct IS NULL THEN NULL WHEN clg_valve_pct > 1.0 THEN clg_valve_pct / 100.0 ELSE clg_valve_pct END AS clg,
    CASE WHEN damper_cmd IS NULL THEN NULL WHEN damper_cmd > 1.0 THEN damper_cmd / 100.0 ELSE damper_cmd END AS dcmd,
    CASE WHEN damper_pct IS NULL THEN NULL WHEN damper_pct > 1.0 THEN damper_pct / 100.0 ELSE damper_pct END AS dpos,
    CASE
      WHEN fan_status IS NOT NULL THEN CASE WHEN fan_status > 0.05 THEN 1 ELSE 0 END
      WHEN fan_cmd IS NOT NULL THEN CASE WHEN (CASE WHEN fan_cmd > 1.0 THEN fan_cmd / 100.0 ELSE fan_cmd END) > 0.10 THEN 1 ELSE 0 END
      ELSE 0
    END AS fan_on
  FROM history
), base AS (
  SELECT equipment_id, timestamp_utc,
    CAST(CASE WHEN fan_on = 1 AND dcmd IS NOT NULL AND dpos IS NOT NULL AND dcmd >= 0.15 AND dcmd - dpos > 0.15 THEN 1 ELSE 0 END AS INT) AS raw_fault
  FROM normalized
), lagged AS (
  SELECT *, CASE WHEN raw_fault = LAG(raw_fault) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc) THEN 0 ELSE 1 END AS is_new_streak
  FROM base
), grouped AS (
  SELECT *, SUM(is_new_streak) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS UNBOUNDED PRECEDING) AS streak_id
  FROM lagged
), ranked AS (
  SELECT *, ROW_NUMBER() OVER (PARTITION BY equipment_id, streak_id ORDER BY timestamp_utc) AS streak_len
  FROM grouped
)
SELECT equipment_id,
  SUM(CASE WHEN raw_fault = 1 AND streak_len >= 3 THEN 1 ELSE 0 END) * 300 / 3600.0 AS fault_hours
FROM ranked
GROUP BY equipment_id;

EXECUTE fdd_rule_71;
DEALLOCATE fdd_rule_71;

-- FCU-CO2-DAMPER
PREPARE fdd_rule_72 AS
-- PostgreSQL adaptation. Render numeric template parameters with render_rule.py.
-- Inputs must be scoped to one tenant/site and cadence; see README.md.
-- fcu_co2_damper.sql — first-class FCU screening rule
WITH normalized AS (
  SELECT equipment_id, timestamp_utc, sat, zone_t, zone_co2,
    CASE WHEN htg_valve_pct IS NULL THEN NULL WHEN htg_valve_pct > 1.0 THEN htg_valve_pct / 100.0 ELSE htg_valve_pct END AS htg,
    CASE WHEN clg_valve_pct IS NULL THEN NULL WHEN clg_valve_pct > 1.0 THEN clg_valve_pct / 100.0 ELSE clg_valve_pct END AS clg,
    CASE WHEN damper_cmd IS NULL THEN NULL WHEN damper_cmd > 1.0 THEN damper_cmd / 100.0 ELSE damper_cmd END AS dcmd,
    CASE WHEN damper_pct IS NULL THEN NULL WHEN damper_pct > 1.0 THEN damper_pct / 100.0 ELSE damper_pct END AS dpos,
    CASE
      WHEN fan_status IS NOT NULL THEN CASE WHEN fan_status > 0.05 THEN 1 ELSE 0 END
      WHEN fan_cmd IS NOT NULL THEN CASE WHEN (CASE WHEN fan_cmd > 1.0 THEN fan_cmd / 100.0 ELSE fan_cmd END) > 0.10 THEN 1 ELSE 0 END
      ELSE 0
    END AS fan_on
  FROM history
), base AS (
  SELECT equipment_id, timestamp_utc,
    CAST(CASE WHEN fan_on = 1 AND zone_co2 IS NOT NULL AND zone_co2 > 1000 AND zone_co2 >= 300.0 AND dcmd IS NOT NULL AND dcmd < 0.1 THEN 1 ELSE 0 END AS INT) AS raw_fault
  FROM normalized
), lagged AS (
  SELECT *, CASE WHEN raw_fault = LAG(raw_fault) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc) THEN 0 ELSE 1 END AS is_new_streak
  FROM base
), grouped AS (
  SELECT *, SUM(is_new_streak) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS UNBOUNDED PRECEDING) AS streak_id
  FROM lagged
), ranked AS (
  SELECT *, ROW_NUMBER() OVER (PARTITION BY equipment_id, streak_id ORDER BY timestamp_utc) AS streak_len
  FROM grouped
)
SELECT equipment_id,
  SUM(CASE WHEN raw_fault = 1 AND streak_len >= 3 THEN 1 ELSE 0 END) * 300 / 3600.0 AS fault_hours
FROM ranked
GROUP BY equipment_id;

EXECUTE fdd_rule_72;
DEALLOCATE fdd_rule_72;

-- FCU-DEADBAND
PREPARE fdd_rule_73 AS
-- PostgreSQL adaptation. Render numeric template parameters with render_rule.py.
-- Inputs must be scoped to one tenant/site and cadence; see README.md.
-- FCU-DEADBAND — pass-through FCU setpoints remain site-native Celsius
SELECT equipment_id,
  SUM(CASE WHEN cooling_sp IS NOT NULL AND heating_sp IS NOT NULL
    AND cooling_sp - heating_sp < 1 THEN 1 ELSE 0 END)
    * 300 / 3600.0 AS fault_hours
FROM history
GROUP BY equipment_id;

EXECUTE fdd_rule_73;
DEALLOCATE fdd_rule_73;

-- FCU-MODE-CYCLE
PREPARE fdd_rule_74 AS
-- PostgreSQL adaptation. Render numeric template parameters with render_rule.py.
-- Inputs must be scoped to one tenant/site and cadence; see README.md.
-- FCU-MODE-CYCLE — cumulative heat/cool mode transitions in the analysis window
WITH modes AS (
  SELECT equipment_id, timestamp_utc,
    CASE
      WHEN clg_valve_pct IS NOT NULL AND (CASE WHEN clg_valve_pct > 1.0 THEN clg_valve_pct / 100.0 ELSE clg_valve_pct END) > 0.1 THEN -1
      WHEN htg_valve_pct IS NOT NULL AND (CASE WHEN htg_valve_pct > 1.0 THEN htg_valve_pct / 100.0 ELSE htg_valve_pct END) > 0.1 THEN 1
      ELSE 0
    END AS mode
  FROM history
), active_modes AS (
  SELECT equipment_id, timestamp_utc, mode
  FROM modes WHERE mode <> 0
), changes AS (
  SELECT equipment_id, timestamp_utc, mode,
    CASE WHEN LAG(mode) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc) IS NOT NULL
      AND mode <> LAG(mode) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc)
      THEN 1 ELSE 0 END AS changed
  FROM active_modes
), cumulative AS (
  SELECT equipment_id, timestamp_utc,
    SUM(changed) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS UNBOUNDED PRECEDING) AS change_count
  FROM changes
)
SELECT equipment_id,
  SUM(CASE WHEN change_count >= 4 THEN 1 ELSE 0 END)
    * 300 / 3600.0 AS fault_hours
FROM cumulative
GROUP BY equipment_id;

EXECUTE fdd_rule_74;
DEALLOCATE fdd_rule_74;

-- UTIL-MONTHLY
PREPARE fdd_rule_75 AS
-- PostgreSQL adaptation. Render numeric template parameters with render_rule.py.
-- Inputs must be scoped to one tenant/site and cadence; see README.md.
-- util_monthly_fault.sql — BAS monthly kWh vs utility monthly bills (% deviation)
WITH bas_monthly AS (
  SELECT
    to_char(timestamp_utc AT TIME ZONE 'UTC', 'YYYY-MM') AS billing_period,
    SUM(
      COALESCE(
        CAST(kwh AS DOUBLE PRECISION),
        CAST(electric_kw AS DOUBLE PRECISION) * 300 / 3600.0,
        0.0
      )
    ) AS bas_kwh
  FROM history
  WHERE kwh IS NOT NULL OR electric_kw IS NOT NULL
  GROUP BY 1
),
util AS (
  SELECT
    billing_period,
    CAST(kwh AS DOUBLE PRECISION) AS util_kwh
  FROM utility_monthly
  WHERE kwh IS NOT NULL
),
joined AS (
  SELECT
    u.billing_period,
    u.util_kwh,
    COALESCE(b.bas_kwh, 0.0) AS bas_kwh,
    CASE
      WHEN u.util_kwh IS NULL OR u.util_kwh <= 0 THEN 0
      WHEN ABS(COALESCE(b.bas_kwh, 0.0) - u.util_kwh) / u.util_kwh * 100.0 > 10
      THEN 1
      ELSE 0
    END AS raw_fault
  FROM util u
  LEFT JOIN bas_monthly b ON b.billing_period = u.billing_period
)
SELECT
  '__UTIL_MONTHLY__' AS equipment_id,
  CAST(SUM(raw_fault) AS DOUBLE PRECISION) * 720.0 AS fault_hours
FROM joined;

EXECUTE fdd_rule_75;
DEALLOCATE fdd_rule_75;

-- UTIL-INTERVAL
PREPARE fdd_rule_76 AS
-- PostgreSQL adaptation. Render numeric template parameters with render_rule.py.
-- Inputs must be scoped to one tenant/site and cadence; see README.md.
-- util_interval_fault.sql — BAS 15m vs utility interval (rolling MAE proxy)
WITH bas AS (
  SELECT
    timestamp_utc,
    COALESCE(
      CAST(kwh AS DOUBLE PRECISION),
      CAST(electric_kw AS DOUBLE PRECISION) * 300 / 3600.0
    ) AS bas_kwh
  FROM history
  WHERE kwh IS NOT NULL OR electric_kw IS NOT NULL
),
util AS (
  SELECT
    timestamp_utc,
    CAST(kwh AS DOUBLE PRECISION) AS util_kwh
  FROM utility_interval
  WHERE kwh IS NOT NULL
),
joined AS (
  SELECT
    b.timestamp_utc,
    ABS(COALESCE(b.bas_kwh, 0.0) - COALESCE(u.util_kwh, 0.0)) AS abs_err
  FROM bas b
  INNER JOIN util u ON b.timestamp_utc = u.timestamp_utc
),
agg AS (
  SELECT
  AVG(abs_err) AS mae
  FROM joined
)
SELECT
  '__UTIL_INTERVAL__' AS equipment_id,
  CASE
    WHEN (SELECT COUNT(*) FROM util) = 0 THEN 0.0
    WHEN mae > 5 THEN 720.0
    ELSE 0.0
  END AS fault_hours
FROM agg;

EXECUTE fdd_rule_76;
DEALLOCATE fdd_rule_76;
ROLLBACK;
