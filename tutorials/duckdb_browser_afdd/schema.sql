-- A small learning schema inspired by Normal Framework and Open-FDD.
-- Supply-air temperature is degrees Celsius; cooling_enabled is 0 or 1.
-- All timestamps use UTC.

-- 1. RAW HISTORIAN: one stored value per point and timestamp.
CREATE SCHEMA IF NOT EXISTS nf;
CREATE TABLE IF NOT EXISTS nf.data (
    point_id VARCHAR,
    time TIMESTAMPTZ,
    value DOUBLE,
    PRIMARY KEY (point_id, time)
);

-- 2. POINT MAP: which sensor belongs to which AHU?
CREATE SCHEMA IF NOT EXISTS fdd;
CREATE TABLE IF NOT EXISTS fdd.point (
    point_key VARCHAR PRIMARY KEY,
    equipment_id VARCHAR,
    role VARCHAR
);

-- 3. ADAPTER VIEW: raw samples joined to their roles.
CREATE OR REPLACE VIEW fdd.input_sample AS
SELECT p.equipment_id, p.role, d.time AS ts, d.value
FROM nf.data d JOIN fdd.point p ON d.point_id = p.point_key;

-- 4. RESULTS: save each assessment for the latest simulated one-hour window.
-- fault_samples counts hot, cooling-enabled samples; unknown is NULL.
CREATE TABLE IF NOT EXISTS fdd.rule_result (
    equipment_id VARCHAR,
    rule_id VARCHAR,
    window_end TIMESTAMPTZ,
    status VARCHAR,
    fault_samples INTEGER,
    PRIMARY KEY (equipment_id, rule_id, window_end)
);
