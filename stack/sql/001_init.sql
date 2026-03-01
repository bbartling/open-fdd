-- TimescaleDB extension only. Legacy weather tables (weather_hourly_raw, weather_fault_daily,
-- weather_fault_events) were removed; weather data lives in timeseries_readings (002 + open_meteo).
-- Existing DBs: run 014_drop_legacy_weather_tables.sql to drop the old tables.
CREATE EXTENSION IF NOT EXISTS timescaledb;
