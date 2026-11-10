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
base_history AS (
  SELECT base_proof.*,
    MAX(EXTRACT(EPOCH FROM timestamp_utc)) OVER (PARTITION BY equipment_id) AS observed_end_epoch,
    100.0 * AVG(energized) OVER (PARTITION BY equipment_id) AS coverage_pct
  FROM base_proof
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
  WHERE sensor_role IN ({{ASSESSABLE_ROLES}})
  GROUP BY equipment_id, series_id, sensor_role
),
sensor_rows AS (
  SELECT s.equipment_id, s.series_id, s.sensor_role, s.timestamp_utc,
    CASE WHEN hs.observed_end_epoch IS NULL OR MAX(EXTRACT(EPOCH FROM s.timestamp_utc)) OVER (PARTITION BY s.equipment_id) > hs.observed_end_epoch
      THEN MAX(EXTRACT(EPOCH FROM s.timestamp_utc)) OVER (PARTITION BY s.equipment_id) ELSE hs.observed_end_epoch END AS observed_end_epoch,
    COALESCE(bh.energized, 1) AS energized,
    COALESCE(hs.coverage_pct, 100.0) AS coverage_pct,
    EXTRACT(EPOCH FROM s.timestamp_utc) AS epoch_seconds,
    fdd.mask_sweep_val(s.sensor_role, s.unit, s.value) AS value
  FROM sensor_history s
  LEFT JOIN base_history bh
    ON bh.equipment_id = s.equipment_id AND bh.timestamp_utc = s.timestamp_utc
  LEFT JOIN equipment_summary hs
    ON hs.equipment_id = s.equipment_id
  WHERE s.value IS NOT NULL
    AND s.sensor_role IN ({{ASSESSABLE_ROLES}})
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
    SUM(CASE WHEN value IS NULL OR previous_value IS NULL OR previous_epoch IS NULL OR epoch_seconds - previous_epoch > {{MAX_SILENCE_SECONDS}} THEN 1 ELSE 0 END)
      OVER (PARTITION BY equipment_id, series_id ORDER BY epoch_seconds ROWS UNBOUNDED PRECEDING) AS data_segment
  FROM prior
),
valid AS (
  SELECT * FROM prior_groups WHERE value IS NOT NULL
),
windowed AS (
  SELECT valid.*
  FROM valid
),
signals AS (
  SELECT windowed.*,
    CASE WHEN next_epoch IS NULL OR next_epoch <= epoch_seconds THEN 0.0
         ELSE next_epoch - epoch_seconds END AS dt_seconds,
    CAST(CASE WHEN ((({{REQUIRE_OPERATIONAL_GATE}} < 0.5 OR (energized = 1 AND coverage_pct >= {{MINIMUM_ACTIVE_COVERAGE_PCT}})) AND ((sensor_role = 'oa_t' AND previous_value IS NOT NULL AND epoch_seconds - previous_epoch <= {{MAX_SILENCE_SECONDS}} AND ABS(value - previous_value) > 20.0 * {{SPIKE_SCALE_TEMPERATURE}}) OR (sensor_role = 'mat' AND previous_value IS NOT NULL AND epoch_seconds - previous_epoch <= {{MAX_SILENCE_SECONDS}} AND ABS(value - previous_value) > 13.888889 * {{SPIKE_SCALE_TEMPERATURE}}) OR (sensor_role = 'zone_t' AND previous_value IS NOT NULL AND epoch_seconds - previous_epoch <= {{MAX_SILENCE_SECONDS}} AND ABS(value - previous_value) > 6.666667 * {{SPIKE_SCALE_TEMPERATURE}}) OR (sensor_role = 'rat' AND previous_value IS NOT NULL AND epoch_seconds - previous_epoch <= {{MAX_SILENCE_SECONDS}} AND ABS(value - previous_value) > 6.666667 * {{SPIKE_SCALE_TEMPERATURE}}) OR (sensor_role = 'sat' AND previous_value IS NOT NULL AND epoch_seconds - previous_epoch <= {{MAX_SILENCE_SECONDS}} AND ABS(value - previous_value) > 22.222222 * {{SPIKE_SCALE_TEMPERATURE}}) OR (sensor_role = 'chw_supply_t' AND previous_value IS NOT NULL AND epoch_seconds - previous_epoch <= {{MAX_SILENCE_SECONDS}} AND ABS(value - previous_value) > 11.111111 * {{SPIKE_SCALE_TEMPERATURE}}) OR (sensor_role = 'chw_return_t' AND previous_value IS NOT NULL AND epoch_seconds - previous_epoch <= {{MAX_SILENCE_SECONDS}} AND ABS(value - previous_value) > 11.111111 * {{SPIKE_SCALE_TEMPERATURE}}) OR (sensor_role = 'hw_supply_t' AND previous_value IS NOT NULL AND epoch_seconds - previous_epoch <= {{MAX_SILENCE_SECONDS}} AND ABS(value - previous_value) > 33.333333 * {{SPIKE_SCALE_TEMPERATURE}}) OR (sensor_role = 'hw_return_t' AND previous_value IS NOT NULL AND epoch_seconds - previous_epoch <= {{MAX_SILENCE_SECONDS}} AND ABS(value - previous_value) > 33.333333 * {{SPIKE_SCALE_TEMPERATURE}}) OR (sensor_role = 'oa_h' AND previous_value IS NOT NULL AND epoch_seconds - previous_epoch <= {{MAX_SILENCE_SECONDS}} AND ABS(value - previous_value) > 25.0 * {{SPIKE_SCALE_HUMIDITY}}) OR (sensor_role = 'duct_static' AND previous_value IS NOT NULL AND epoch_seconds - previous_epoch <= {{MAX_SILENCE_SECONDS}} AND ABS(value - previous_value) > 497.68 * {{SPIKE_SCALE_PRESSURE}})))) THEN 1 ELSE 0 END AS INT) AS raw_fault
  FROM windowed
),
segments AS (
  SELECT signals.*,
    CASE WHEN dt_seconds <= 0 THEN 0.0
         WHEN dt_seconds < {{MAX_SILENCE_SECONDS}} THEN dt_seconds
         ELSE {{MAX_SILENCE_SECONDS}} END AS normal_seconds,
    CASE WHEN dt_seconds > {{MAX_SILENCE_SECONDS}}
         THEN dt_seconds - {{MAX_SILENCE_SECONDS}} ELSE 0.0 END AS silence_seconds
  FROM signals
),
lagged AS (
  SELECT segments.*,
    COALESCE(LAG(raw_fault) OVER (PARTITION BY equipment_id, series_id ORDER BY epoch_seconds), 0) AS previous_raw_fault
  FROM segments
),
streak_groups AS (
  SELECT segments.*,
    SUM(CASE WHEN (raw_fault = 1 AND previous_raw_fault = 0) OR raw_fault = 0
             THEN 1 ELSE 0 END) OVER (
      PARTITION BY equipment_id, series_id, data_segment ORDER BY epoch_seconds ROWS UNBOUNDED PRECEDING
    ) AS streak_group
  FROM lagged segments
),
streaks AS (
  SELECT streak_groups.*,
    SUM(CASE WHEN raw_fault = 1 THEN normal_seconds ELSE 0.0 END) OVER (
      PARTITION BY equipment_id, series_id, data_segment, streak_group
      ORDER BY epoch_seconds ROWS UNBOUNDED PRECEDING
    ) AS fault_streak_seconds
  FROM streak_groups
),
confirmed_rows AS (
  SELECT streaks.*,
    CASE WHEN raw_fault = 1 AND fault_streak_seconds >= {{CONFIRM_SECONDS}} THEN 1 ELSE 0 END AS normal_confirmed
  FROM streaks
),
final AS (
  SELECT equipment_id, series_id, sensor_role, epoch_seconds AS segment_epoch,
    normal_confirmed AS confirmed, normal_seconds AS held_seconds
  FROM confirmed_rows WHERE normal_seconds > 0
  UNION ALL
  SELECT equipment_id, series_id, sensor_role,
    epoch_seconds + {{MAX_SILENCE_SECONDS}} AS segment_epoch,
    1 AS confirmed, silence_seconds AS held_seconds
  FROM confirmed_rows WHERE silence_seconds > 0
),
scored AS (
  SELECT equipment_id, series_id, sensor_role,
    SUM(CASE WHEN confirmed = 1 THEN held_seconds ELSE 0.0 END) / 3600.0 AS fault_hours,
    SUM(held_seconds) / 3600.0 AS covered_hours
  FROM final
  GROUP BY equipment_id, series_id, sensor_role
)
SELECT ss.equipment_id, ss.series_id, ss.sensor_role,
  CASE WHEN COALESCE(scored.covered_hours, 0.0) > 0 THEN COALESCE(scored.fault_hours, 0.0) ELSE NULL END AS fault_hours,
  COALESCE(scored.covered_hours, 0.0) AS covered_hours
FROM sensor_series ss
LEFT JOIN scored USING (equipment_id, series_id, sensor_role)
ORDER BY ss.equipment_id, ss.series_id;
