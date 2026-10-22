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
       ) < {{ECON1_DAMPER_MAX}}
       AND CAST(oa_t AS DOUBLE PRECISION) > {{ECON1_OAT_MIN}}
      THEN 1 ELSE 0 END AS INT) AS raw_fault
  FROM history
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
