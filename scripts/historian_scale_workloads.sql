-- H10 representative DataFusion historian workload suite.
--
-- The production historian is registered as `history` by fdd_sql. Replace the
-- literal scope/time values in a qualification harness; keep building/equipment
-- predicates explicit so file/partition pruning can be measured.

-- workload: equipment/day
SELECT
  building_id,
  equipment_id,
  COUNT(*) AS rows_scanned,
  MIN(timestamp_utc) AS first_sample,
  MAX(timestamp_utc) AS last_sample,
  AVG(supply_air_temperature) AS avg_sat
FROM history
WHERE building_id = 'building-0001'
  AND equipment_id = 'ahu-00001'
  AND timestamp_utc >= TIMESTAMP '2026-01-05T00:00:00Z'
  AND timestamp_utc <  TIMESTAMP '2026-01-06T00:00:00Z'
GROUP BY building_id, equipment_id;

-- workload: equipment/month
SELECT
  building_id,
  equipment_id,
  COUNT(*) AS rows_scanned,
  AVG(outside_air_temperature) AS avg_oat,
  AVG(return_air_temperature) AS avg_rat,
  AVG(supply_air_temperature) AS avg_sat
FROM history
WHERE building_id = 'building-0001'
  AND equipment_id = 'ahu-00001'
  AND year = '2026'
  AND month = '01'
GROUP BY building_id, equipment_id;

-- workload: building/hour
SELECT
  building_id,
  date_trunc('hour', timestamp_utc) AS hour_utc,
  COUNT(*) AS rows_scanned,
  AVG(supply_air_temperature) AS avg_sat,
  AVG(outside_air_damper_command) AS avg_damper
FROM history
WHERE building_id = 'building-0001'
  AND timestamp_utc >= TIMESTAMP '2026-01-05T12:00:00Z'
  AND timestamp_utc <  TIMESTAMP '2026-01-05T13:00:00Z'
GROUP BY building_id, date_trunc('hour', timestamp_utc)
ORDER BY hour_utc;

-- workload: monthly aggregation
SELECT
  building_id,
  equipment_id,
  year,
  month,
  COUNT(*) AS rows_scanned,
  AVG(outside_air_temperature) AS avg_oat,
  AVG(supply_air_temperature) AS avg_sat,
  AVG(return_air_temperature) AS avg_rat
FROM history
WHERE building_id = 'building-0001'
  AND year = '2026'
  AND month = '01'
GROUP BY building_id, equipment_id, year, month
ORDER BY equipment_id;

-- workload: weather join
-- H10 harnesses should run this only when the canonical optional `weather` table
-- is registered. The join intentionally uses a bounded time range and building
-- scope so weather qualification does not turn into a retained-history scan.
SELECT
  h.building_id,
  h.equipment_id,
  date_trunc('hour', h.timestamp_utc) AS hour_utc,
  AVG(h.supply_air_temperature) AS avg_sat,
  AVG(w.outside_air_temperature) AS avg_weather_oat
FROM history h
JOIN weather w
  ON date_trunc('hour', h.timestamp_utc) = date_trunc('hour', w.timestamp_utc)
WHERE h.building_id = 'building-0001'
  AND h.timestamp_utc >= TIMESTAMP '2026-01-05T00:00:00Z'
  AND h.timestamp_utc <  TIMESTAMP '2026-01-06T00:00:00Z'
GROUP BY h.building_id, h.equipment_id, date_trunc('hour', h.timestamp_utc)
ORDER BY h.equipment_id, hour_utc;

-- workload: representative FDD proof query
-- A deliberately simple economizer-style diagnostic proof workload. This does
-- not replace the rule registry; release qualification must also execute the
-- production AFDD registry. It provides a stable SQL benchmark shape that uses
-- multiple role columns and a selective equipment/time predicate.
SELECT
  building_id,
  equipment_id,
  COUNT(*) AS suspect_samples
FROM history
WHERE building_id = 'building-0001'
  AND equipment_id = 'ahu-00001'
  AND timestamp_utc >= TIMESTAMP '2026-01-05T00:00:00Z'
  AND timestamp_utc <  TIMESTAMP '2026-01-06T00:00:00Z'
  AND supply_fan_status > 0.5
  AND outside_air_temperature < return_air_temperature - 5.0
  AND outside_air_damper_command < 20.0
GROUP BY building_id, equipment_id;
