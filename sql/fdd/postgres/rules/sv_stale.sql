-- PostgreSQL adaptation. Render numeric template parameters with render_rule.py.
-- Inputs must be scoped to one tenant/site and cadence; see README.md.
-- sv_stale.sql — Stale data (no fresh samples)
-- Pandas gate is `always` — do not filter fan_cmd (off-period stale still counts).
-- Pandas `_sweep_stale` ANDs FLATLINE_SENSOR_ROLES (SENSOR_LIMITS minus duct static).
-- SQL windows that catalog: five air temps plus chw/hw temps and oa_h.
-- Every mapped analog must sit inside STALE_TOL across the trailing STALE_HOURS
-- window: one live sensor is enough to prove the feed is still updating.
-- {{STALE_ROWS}} / {{STALE_ROWS_PRECEDING}} are derived from STALE_HOURS and
-- POLL_SECONDS (DataFusion requires literal ROWS frame bounds).
WITH win AS (
  SELECT
    equipment_id,
    timestamp_utc,
    COUNT(oa_t) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS BETWEEN {{STALE_ROWS_PRECEDING}} PRECEDING AND CURRENT ROW) AS n_oa_t,
    MAX(oa_t) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS BETWEEN {{STALE_ROWS_PRECEDING}} PRECEDING AND CURRENT ROW)
      - MIN(oa_t) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS BETWEEN {{STALE_ROWS_PRECEDING}} PRECEDING AND CURRENT ROW) AS span_oa_t,
    COUNT(mat) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS BETWEEN {{STALE_ROWS_PRECEDING}} PRECEDING AND CURRENT ROW) AS n_mat,
    MAX(mat) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS BETWEEN {{STALE_ROWS_PRECEDING}} PRECEDING AND CURRENT ROW)
      - MIN(mat) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS BETWEEN {{STALE_ROWS_PRECEDING}} PRECEDING AND CURRENT ROW) AS span_mat,
    COUNT(zone_t) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS BETWEEN {{STALE_ROWS_PRECEDING}} PRECEDING AND CURRENT ROW) AS n_zone_t,
    MAX(zone_t) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS BETWEEN {{STALE_ROWS_PRECEDING}} PRECEDING AND CURRENT ROW)
      - MIN(zone_t) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS BETWEEN {{STALE_ROWS_PRECEDING}} PRECEDING AND CURRENT ROW) AS span_zone_t,
    COUNT(rat) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS BETWEEN {{STALE_ROWS_PRECEDING}} PRECEDING AND CURRENT ROW) AS n_rat,
    MAX(rat) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS BETWEEN {{STALE_ROWS_PRECEDING}} PRECEDING AND CURRENT ROW)
      - MIN(rat) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS BETWEEN {{STALE_ROWS_PRECEDING}} PRECEDING AND CURRENT ROW) AS span_rat,
    COUNT(sat) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS BETWEEN {{STALE_ROWS_PRECEDING}} PRECEDING AND CURRENT ROW) AS n_sat,
    MAX(sat) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS BETWEEN {{STALE_ROWS_PRECEDING}} PRECEDING AND CURRENT ROW)
      - MIN(sat) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS BETWEEN {{STALE_ROWS_PRECEDING}} PRECEDING AND CURRENT ROW) AS span_sat,
    COUNT(chw_supply_t) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS BETWEEN {{STALE_ROWS_PRECEDING}} PRECEDING AND CURRENT ROW) AS n_chw_supply_t,
    MAX(chw_supply_t) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS BETWEEN {{STALE_ROWS_PRECEDING}} PRECEDING AND CURRENT ROW)
      - MIN(chw_supply_t) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS BETWEEN {{STALE_ROWS_PRECEDING}} PRECEDING AND CURRENT ROW) AS span_chw_supply_t,
    COUNT(chw_return_t) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS BETWEEN {{STALE_ROWS_PRECEDING}} PRECEDING AND CURRENT ROW) AS n_chw_return_t,
    MAX(chw_return_t) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS BETWEEN {{STALE_ROWS_PRECEDING}} PRECEDING AND CURRENT ROW)
      - MIN(chw_return_t) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS BETWEEN {{STALE_ROWS_PRECEDING}} PRECEDING AND CURRENT ROW) AS span_chw_return_t,
    COUNT(hw_supply_t) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS BETWEEN {{STALE_ROWS_PRECEDING}} PRECEDING AND CURRENT ROW) AS n_hw_supply_t,
    MAX(hw_supply_t) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS BETWEEN {{STALE_ROWS_PRECEDING}} PRECEDING AND CURRENT ROW)
      - MIN(hw_supply_t) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS BETWEEN {{STALE_ROWS_PRECEDING}} PRECEDING AND CURRENT ROW) AS span_hw_supply_t,
    COUNT(hw_return_t) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS BETWEEN {{STALE_ROWS_PRECEDING}} PRECEDING AND CURRENT ROW) AS n_hw_return_t,
    MAX(hw_return_t) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS BETWEEN {{STALE_ROWS_PRECEDING}} PRECEDING AND CURRENT ROW)
      - MIN(hw_return_t) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS BETWEEN {{STALE_ROWS_PRECEDING}} PRECEDING AND CURRENT ROW) AS span_hw_return_t,
    COUNT(oa_h) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS BETWEEN {{STALE_ROWS_PRECEDING}} PRECEDING AND CURRENT ROW) AS n_oa_h,
    MAX(oa_h) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS BETWEEN {{STALE_ROWS_PRECEDING}} PRECEDING AND CURRENT ROW)
      - MIN(oa_h) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS BETWEEN {{STALE_ROWS_PRECEDING}} PRECEDING AND CURRENT ROW) AS span_oa_h,
    COUNT(ra_h) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS BETWEEN {{STALE_ROWS_PRECEDING}} PRECEDING AND CURRENT ROW) AS n_ra_h,
    MAX(ra_h) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS BETWEEN {{STALE_ROWS_PRECEDING}} PRECEDING AND CURRENT ROW)
      - MIN(ra_h) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS BETWEEN {{STALE_ROWS_PRECEDING}} PRECEDING AND CURRENT ROW) AS span_ra_h,
    COUNT(zone_rh) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS BETWEEN {{STALE_ROWS_PRECEDING}} PRECEDING AND CURRENT ROW) AS n_zone_rh,
    MAX(zone_rh) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS BETWEEN {{STALE_ROWS_PRECEDING}} PRECEDING AND CURRENT ROW)
      - MIN(zone_rh) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS BETWEEN {{STALE_ROWS_PRECEDING}} PRECEDING AND CURRENT ROW) AS span_zone_rh,
    COUNT(ma_h) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS BETWEEN {{STALE_ROWS_PRECEDING}} PRECEDING AND CURRENT ROW) AS n_ma_h,
    MAX(ma_h) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS BETWEEN {{STALE_ROWS_PRECEDING}} PRECEDING AND CURRENT ROW)
      - MIN(ma_h) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS BETWEEN {{STALE_ROWS_PRECEDING}} PRECEDING AND CURRENT ROW) AS span_ma_h,
    COUNT(sa_h) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS BETWEEN {{STALE_ROWS_PRECEDING}} PRECEDING AND CURRENT ROW) AS n_sa_h,
    MAX(sa_h) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS BETWEEN {{STALE_ROWS_PRECEDING}} PRECEDING AND CURRENT ROW)
      - MIN(sa_h) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS BETWEEN {{STALE_ROWS_PRECEDING}} PRECEDING AND CURRENT ROW) AS span_sa_h
  FROM history
),
scored AS (
  SELECT
    equipment_id,
    timestamp_utc,
    CASE WHEN n_oa_t >= {{STALE_ROWS}} THEN 1 ELSE 0 END
      + CASE WHEN n_mat >= {{STALE_ROWS}} THEN 1 ELSE 0 END
      + CASE WHEN n_zone_t >= {{STALE_ROWS}} THEN 1 ELSE 0 END
      + CASE WHEN n_rat >= {{STALE_ROWS}} THEN 1 ELSE 0 END
      + CASE WHEN n_sat >= {{STALE_ROWS}} THEN 1 ELSE 0 END
      + CASE WHEN n_chw_supply_t >= {{STALE_ROWS}} THEN 1 ELSE 0 END
      + CASE WHEN n_chw_return_t >= {{STALE_ROWS}} THEN 1 ELSE 0 END
      + CASE WHEN n_hw_supply_t >= {{STALE_ROWS}} THEN 1 ELSE 0 END
      + CASE WHEN n_hw_return_t >= {{STALE_ROWS}} THEN 1 ELSE 0 END
      + CASE WHEN n_oa_h >= {{STALE_ROWS}} THEN 1 ELSE 0 END
      + CASE WHEN n_ra_h >= {{STALE_ROWS}} THEN 1 ELSE 0 END
      + CASE WHEN n_zone_rh >= {{STALE_ROWS}} THEN 1 ELSE 0 END
      + CASE WHEN n_ma_h >= {{STALE_ROWS}} THEN 1 ELSE 0 END
      + CASE WHEN n_sa_h >= {{STALE_ROWS}} THEN 1 ELSE 0 END AS roles_mapped,
    CASE WHEN n_oa_t >= {{STALE_ROWS}} AND span_oa_t <= {{STALE_TOL}} THEN 1 ELSE 0 END
      + CASE WHEN n_mat >= {{STALE_ROWS}} AND span_mat <= {{STALE_TOL}} THEN 1 ELSE 0 END
      + CASE WHEN n_zone_t >= {{STALE_ROWS}} AND span_zone_t <= {{STALE_TOL}} THEN 1 ELSE 0 END
      + CASE WHEN n_rat >= {{STALE_ROWS}} AND span_rat <= {{STALE_TOL}} THEN 1 ELSE 0 END
      + CASE WHEN n_sat >= {{STALE_ROWS}} AND span_sat <= {{STALE_TOL}} THEN 1 ELSE 0 END
      + CASE WHEN n_chw_supply_t >= {{STALE_ROWS}} AND span_chw_supply_t <= {{STALE_TOL}} THEN 1 ELSE 0 END
      + CASE WHEN n_chw_return_t >= {{STALE_ROWS}} AND span_chw_return_t <= {{STALE_TOL}} THEN 1 ELSE 0 END
      + CASE WHEN n_hw_supply_t >= {{STALE_ROWS}} AND span_hw_supply_t <= {{STALE_TOL}} THEN 1 ELSE 0 END
      + CASE WHEN n_hw_return_t >= {{STALE_ROWS}} AND span_hw_return_t <= {{STALE_TOL}} THEN 1 ELSE 0 END
      + CASE WHEN n_oa_h >= {{STALE_ROWS}} AND span_oa_h <= {{STALE_TOL}} THEN 1 ELSE 0 END
      + CASE WHEN n_ra_h >= {{STALE_ROWS}} AND span_ra_h <= {{STALE_TOL}} THEN 1 ELSE 0 END
      + CASE WHEN n_zone_rh >= {{STALE_ROWS}} AND span_zone_rh <= {{STALE_TOL}} THEN 1 ELSE 0 END
      + CASE WHEN n_ma_h >= {{STALE_ROWS}} AND span_ma_h <= {{STALE_TOL}} THEN 1 ELSE 0 END
      + CASE WHEN n_sa_h >= {{STALE_ROWS}} AND span_sa_h <= {{STALE_TOL}} THEN 1 ELSE 0 END AS roles_stale
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
