-- Drop legacy weather tables from pre–graph/RDF design.
-- Weather data now lives in timeseries_readings (points + open_meteo driver).
-- Safe to run on DBs that never had these tables (IF EXISTS).
DROP TABLE IF EXISTS weather_fault_events;
DROP TABLE IF EXISTS weather_fault_daily;
DROP TABLE IF EXISTS weather_hourly_raw;
