-- PostgreSQL adaptation. Render numeric template parameters with render_rule.py.
-- Sensor-series input and output are keyed by the bound point UUID, not the role.
WITH base_proof AS (
  SELECT h.*,
    CASE
      WHEN h.fan_status IS NOT NULL THEN CASE WHEN h.fan_status > 0.05 THEN 1 ELSE 0 END
      WHEN h.fan_cmd IS NOT NULL THEN CASE WHEN h.fan_cmd > 0.01 THEN 1 ELSE 0 END
      WHEN h.zone_flow IS NOT NULL THEN CASE WHEN h.zone_flow > 23.597350 THEN 1 ELSE 0 END
      WHEN h.pump_status IS NOT NULL THEN CASE WHEN h.pump_status > 0.05 THEN 1 ELSE 0 END
      WHEN h.chw_pump_cmd IS NOT NULL THEN CASE WHEN h.chw_pump_cmd > 0.05 THEN 1 ELSE 0 END
      WHEN h.chiller_status IS NOT NULL THEN CASE WHEN h.chiller_status > 0.05 THEN 1 ELSE 0 END
      ELSE 1 END AS energized
  FROM history h
),
equipment_summary AS (
  SELECT equipment_id,
    MAX(EXTRACT(EPOCH FROM timestamp_utc)) AS observed_end_epoch,
    100.0 * AVG(energized) AS coverage_pct
  FROM base_proof
  GROUP BY equipment_id
),
sensor_series AS (
  SELECT equipment_id, series_id, sensor_role
  FROM sensor_history
  GROUP BY equipment_id, series_id, sensor_role
),
sensor_rows AS (
  SELECT s.equipment_id, s.series_id, s.sensor_role, s.timestamp_utc,
    CASE WHEN hs.observed_end_epoch IS NULL OR MAX(EXTRACT(EPOCH FROM s.timestamp_utc)) OVER (PARTITION BY s.equipment_id) > hs.observed_end_epoch
      THEN MAX(EXTRACT(EPOCH FROM s.timestamp_utc)) OVER (PARTITION BY s.equipment_id) ELSE hs.observed_end_epoch END AS observed_end_epoch,
    COALESCE(hs.coverage_pct, 100.0) AS coverage_pct,
    EXTRACT(EPOCH FROM s.timestamp_utc) AS epoch_seconds,
    CASE WHEN s.sensor_role IN ('oa_t', 'mat', 'zone_t', 'rat', 'sat')
      THEN fdd.mask_sweep_val(s.sensor_role, s.unit, s.value) ELSE NULL END AS value
  FROM sensor_history s
  LEFT JOIN equipment_summary hs
    ON hs.equipment_id = s.equipment_id
  WHERE s.value IS NOT NULL
),
prior AS (
  SELECT sensor_rows.*,
    LAG(value) OVER (PARTITION BY equipment_id, series_id ORDER BY epoch_seconds) AS previous_value,
    COALESCE(LEAD(epoch_seconds) OVER (PARTITION BY equipment_id, series_id ORDER BY epoch_seconds), observed_end_epoch) AS next_epoch,
    LAG(epoch_seconds) OVER (PARTITION BY equipment_id, series_id ORDER BY epoch_seconds) AS previous_epoch
  FROM sensor_rows
),
prior_groups AS (
  SELECT prior.*,
    SUM(CASE WHEN value IS NULL OR previous_value IS NULL OR previous_epoch IS NULL
                  OR epoch_seconds - previous_epoch > {{MAX_GAP_HOURS}} * 3600.0
             THEN 1 ELSE 0 END)
      OVER (PARTITION BY equipment_id, series_id ORDER BY epoch_seconds ROWS UNBOUNDED PRECEDING) AS data_segment
  FROM prior
),
valid AS (
  SELECT * FROM prior_groups WHERE value IS NOT NULL
),
rates AS (
  SELECT valid.*,
    (epoch_seconds - previous_epoch) / 3600.0 AS dt_hours,
    ABS(value - previous_value) AS delta
  FROM valid
),
flagged AS (
  SELECT rates.*,
    CAST(CASE
      WHEN previous_epoch IS NULL OR epoch_seconds - previous_epoch > {{MAX_GAP_HOURS}} * 3600.0 THEN 0
      WHEN dt_hours IS NULL OR dt_hours <= 0.0 THEN 0
      WHEN delta / dt_hours > ({{STEADY_FAULT_PER_HOUR}} * {{SENSOR_SPAN}} / 100.0) THEN 1
      ELSE 0
    END AS INT) AS over_rate
  FROM rates
),
lagged AS (
  SELECT flagged.*,
    COALESCE(LAG(over_rate) OVER (PARTITION BY equipment_id, series_id ORDER BY epoch_seconds), 0) AS previous_over_rate
  FROM flagged
),
base AS (
  SELECT lagged.*,
    CAST(CASE WHEN over_rate = 1 AND previous_over_rate = 1 THEN 1 ELSE 0 END AS INT) AS raw_fault,
    CASE WHEN next_epoch IS NULL OR next_epoch <= epoch_seconds THEN 0.0
         WHEN next_epoch - epoch_seconds > {{MAX_GAP_HOURS}} * 3600.0 THEN 0.0
         ELSE next_epoch - epoch_seconds END AS held_seconds
  FROM lagged
),
streak_groups AS (
  SELECT base.*,
    COALESCE(LAG(raw_fault) OVER (PARTITION BY equipment_id, series_id ORDER BY epoch_seconds), 0) AS previous_raw_fault
  FROM base
),
streaks AS (
  SELECT streak_groups.*,
    SUM(CASE WHEN (raw_fault = 1 AND previous_raw_fault = 0) OR raw_fault = 0
             THEN 1 ELSE 0 END) OVER (
      PARTITION BY equipment_id, series_id, data_segment ORDER BY epoch_seconds ROWS UNBOUNDED PRECEDING
    ) AS streak_group
  FROM streak_groups
),
confirmed_rows AS (
  SELECT streaks.*,
    SUM(CASE WHEN raw_fault = 1 THEN held_seconds ELSE 0.0 END) OVER (
      PARTITION BY equipment_id, series_id, data_segment, streak_group
      ORDER BY epoch_seconds ROWS UNBOUNDED PRECEDING
    ) AS fault_streak_seconds
  FROM streaks
),
final AS (
  SELECT equipment_id, series_id, sensor_role, epoch_seconds AS segment_epoch,
    CASE WHEN raw_fault = 1 AND fault_streak_seconds >= {{CONFIRM_SECONDS}} THEN 1 ELSE 0 END AS confirmed,
    held_seconds
  FROM confirmed_rows WHERE held_seconds > 0
),
scored AS (
  SELECT equipment_id, series_id, sensor_role,
    SUM(CASE WHEN confirmed = 1 THEN held_seconds ELSE 0.0 END) / 3600.0 AS fault_hours,
    SUM(held_seconds) / 3600.0 AS covered_hours
  FROM final
  GROUP BY equipment_id, series_id, sensor_role
)
SELECT ss.equipment_id, ss.series_id, ss.sensor_role,
  COALESCE(scored.fault_hours, 0.0) AS fault_hours,
  COALESCE(scored.covered_hours, 0.0) AS covered_hours
FROM sensor_series ss
LEFT JOIN scored USING (equipment_id, series_id, sensor_role)
ORDER BY ss.equipment_id, ss.series_id;
