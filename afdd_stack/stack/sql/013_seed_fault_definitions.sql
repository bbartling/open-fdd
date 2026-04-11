INSERT INTO fault_definitions (fault_id, name, description, severity, category)
VALUES ('bad_sensor_flag', 'Bad sensor', 'Sensor stuck, invalid, or out-of-range', 'warning', 'sensor_validation')
ON CONFLICT (fault_id) DO UPDATE
SET
  name = EXCLUDED.name,
  description = EXCLUDED.description,
  severity = EXCLUDED.severity,
  category = EXCLUDED.category,
  updated_at = now();