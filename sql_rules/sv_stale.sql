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
      - MIN(oa_h) OVER (PARTITION BY equipment_id ORDER BY timestamp_utc ROWS BETWEEN {{STALE_ROWS_PRECEDING}} PRECEDING AND CURRENT ROW) AS span_oa_h
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
      + CASE WHEN n_oa_h >= {{STALE_ROWS}} THEN 1 ELSE 0 END AS roles_mapped,
    CASE WHEN n_oa_t >= {{STALE_ROWS}} AND span_oa_t <= {{STALE_TOL}} THEN 1 ELSE 0 END
      + CASE WHEN n_mat >= {{STALE_ROWS}} AND span_mat <= {{STALE_TOL}} THEN 1 ELSE 0 END
      + CASE WHEN n_zone_t >= {{STALE_ROWS}} AND span_zone_t <= {{STALE_TOL}} THEN 1 ELSE 0 END
      + CASE WHEN n_rat >= {{STALE_ROWS}} AND span_rat <= {{STALE_TOL}} THEN 1 ELSE 0 END
      + CASE WHEN n_sat >= {{STALE_ROWS}} AND span_sat <= {{STALE_TOL}} THEN 1 ELSE 0 END
      + CASE WHEN n_chw_supply_t >= {{STALE_ROWS}} AND span_chw_supply_t <= {{STALE_TOL}} THEN 1 ELSE 0 END
      + CASE WHEN n_chw_return_t >= {{STALE_ROWS}} AND span_chw_return_t <= {{STALE_TOL}} THEN 1 ELSE 0 END
      + CASE WHEN n_hw_supply_t >= {{STALE_ROWS}} AND span_hw_supply_t <= {{STALE_TOL}} THEN 1 ELSE 0 END
      + CASE WHEN n_hw_return_t >= {{STALE_ROWS}} AND span_hw_return_t <= {{STALE_TOL}} THEN 1 ELSE 0 END
      + CASE WHEN n_oa_h >= {{STALE_ROWS}} AND span_oa_h <= {{STALE_TOL}} THEN 1 ELSE 0 END AS roles_stale
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
    CASE WHEN raw_fault = 1 AND streak_len >= {{CONFIRM_ROWS}} THEN 1 ELSE 0 END AS confirmed
  FROM ranked
)
SELECT
  equipment_id,
  SUM(confirmed) * {{POLL_SECONDS}} / 3600.0 AS fault_hours
FROM final
GROUP BY equipment_id;
