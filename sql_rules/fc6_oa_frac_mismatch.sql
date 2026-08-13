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
      WHEN mat IS NULL OR rat IS NULL OR oa_t IS NULL OR fan IS NULL THEN 0
      WHEN vav_total_flow IS NULL OR vav_total_flow <= 0.0 THEN 0
      WHEN fan < 0.05 THEN 0
      WHEN ABS(rat - oa_t) < {{DELTA_T_MIN}} THEN 0
      WHEN ABS((mat - rat) / NULLIF(oa_t - rat, 0)
               - {{MIN_CFM_DESIGN}} / NULLIF(vav_total_flow, 0)) > {{AIRFLOW_ERR}} THEN 1
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
