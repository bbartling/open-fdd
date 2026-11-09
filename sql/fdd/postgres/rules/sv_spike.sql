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
sensor_rows_raw AS (
  SELECT equipment_id, 'oa_t' AS sensor_role, timestamp_utc, observed_end_epoch, energized, coverage_pct, oa_t AS value FROM base_history
  UNION ALL
  SELECT equipment_id, 'mat' AS sensor_role, timestamp_utc, observed_end_epoch, energized, coverage_pct, mat AS value FROM base_history
  UNION ALL
  SELECT equipment_id, 'zone_t' AS sensor_role, timestamp_utc, observed_end_epoch, energized, coverage_pct, zone_t AS value FROM base_history
  UNION ALL
  SELECT equipment_id, 'rat' AS sensor_role, timestamp_utc, observed_end_epoch, energized, coverage_pct, rat AS value FROM base_history
  UNION ALL
  SELECT equipment_id, 'sat' AS sensor_role, timestamp_utc, observed_end_epoch, energized, coverage_pct, sat AS value FROM base_history
  UNION ALL
  SELECT equipment_id, 'chw_supply_t' AS sensor_role, timestamp_utc, observed_end_epoch, energized, coverage_pct, chw_supply_t AS value FROM base_history
  UNION ALL
  SELECT equipment_id, 'chw_return_t' AS sensor_role, timestamp_utc, observed_end_epoch, energized, coverage_pct, chw_return_t AS value FROM base_history
  UNION ALL
  SELECT equipment_id, 'hw_supply_t' AS sensor_role, timestamp_utc, observed_end_epoch, energized, coverage_pct, hw_supply_t AS value FROM base_history
  UNION ALL
  SELECT equipment_id, 'hw_return_t' AS sensor_role, timestamp_utc, observed_end_epoch, energized, coverage_pct, hw_return_t AS value FROM base_history
  UNION ALL
  SELECT equipment_id, 'oa_h' AS sensor_role, timestamp_utc, observed_end_epoch, energized, coverage_pct, oa_h AS value FROM base_history
  UNION ALL
  SELECT equipment_id, 'duct_static' AS sensor_role, timestamp_utc, observed_end_epoch, energized, coverage_pct, duct_static AS value FROM base_history
),
authorized AS (
  SELECT a.equipment_id, a.role, MAX(a.unit) AS unit, COUNT(*) AS binding_count
  FROM authorized_series a JOIN equipment e
    ON e.building_id = a.site_id AND e.equipment_id = a.equipment_id
  GROUP BY a.equipment_id, a.role
),
sensor_rows AS (
  SELECT r.equipment_id, r.sensor_role, r.timestamp_utc, r.observed_end_epoch, r.energized, r.coverage_pct,
    fdd.mask_sweep_val(r.sensor_role, a.unit, r.value) AS value
  FROM sensor_rows_raw r
  LEFT JOIN authorized a ON a.equipment_id = r.equipment_id AND a.role = r.sensor_role AND a.binding_count = 1
),
valid AS (
  SELECT equipment_id, sensor_role, timestamp_utc, observed_end_epoch, energized, coverage_pct,
    EXTRACT(EPOCH FROM timestamp_utc) AS epoch_seconds, value
  FROM sensor_rows WHERE value IS NOT NULL
),
prior AS (
  SELECT valid.*,
    LAG(value) OVER (PARTITION BY equipment_id, sensor_role ORDER BY epoch_seconds) AS previous_value,
    COALESCE(LEAD(epoch_seconds) OVER (PARTITION BY equipment_id, sensor_role ORDER BY epoch_seconds), observed_end_epoch) AS next_epoch,
    LAG(epoch_seconds) OVER (PARTITION BY equipment_id, sensor_role ORDER BY epoch_seconds) AS previous_epoch
  FROM valid
),
prior_groups AS (
  SELECT prior.*,
    SUM(CASE WHEN previous_epoch IS NULL OR epoch_seconds - previous_epoch > {{MAX_SILENCE_SECONDS}} THEN 1 ELSE 0 END)
      OVER (PARTITION BY equipment_id, sensor_role ORDER BY epoch_seconds ROWS UNBOUNDED PRECEDING) AS data_segment
  FROM prior
),
windowed AS (
  SELECT prior_groups.*
  FROM prior_groups
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
    COALESCE(LAG(raw_fault) OVER (PARTITION BY equipment_id, sensor_role ORDER BY epoch_seconds), 0) AS previous_raw_fault
  FROM segments
),
streak_groups AS (
  SELECT segments.*,
    SUM(CASE WHEN (raw_fault = 1 AND previous_raw_fault = 0) OR raw_fault = 0
             THEN 1 ELSE 0 END) OVER (
      PARTITION BY equipment_id, sensor_role, data_segment ORDER BY epoch_seconds ROWS UNBOUNDED PRECEDING
    ) AS streak_group
  FROM lagged segments
),
streaks AS (
  SELECT streak_groups.*,
    SUM(CASE WHEN raw_fault = 1 THEN normal_seconds ELSE 0.0 END) OVER (
      PARTITION BY equipment_id, sensor_role, data_segment, streak_group
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
  SELECT equipment_id, sensor_role, epoch_seconds AS segment_epoch,
    normal_confirmed AS confirmed, normal_seconds AS held_seconds
  FROM confirmed_rows WHERE normal_seconds > 0
  UNION ALL
  SELECT equipment_id, sensor_role,
    epoch_seconds + {{MAX_SILENCE_SECONDS}} AS segment_epoch,
    1 AS confirmed, silence_seconds AS held_seconds
  FROM confirmed_rows WHERE silence_seconds > 0
)

SELECT equipment_id, sensor_role,
  SUM(CASE WHEN confirmed = 1 THEN held_seconds ELSE 0.0 END) / 3600.0 AS fault_hours
FROM final GROUP BY equipment_id, sensor_role;
