CREATE EXTENSION IF NOT EXISTS timescaledb;

CREATE TABLE IF NOT EXISTS weather_hourly_raw (
  ts timestamptz NOT NULL,
  site_id text NOT NULL,
  point_key text NOT NULL,
  value double precision NULL
);

SELECT create_hypertable('weather_hourly_raw', 'ts', if_not_exists => TRUE);

CREATE TABLE IF NOT EXISTS weather_fault_daily (
  site_id text NOT NULL,
  fault_id text NOT NULL,
  day date NOT NULL,
  minutes_in_fault int NOT NULL,
  occurrences int NOT NULL,
  details jsonb NULL
);

CREATE TABLE IF NOT EXISTS weather_fault_events (
  site_id text NOT NULL,
  fault_id text NOT NULL,
  start_ts timestamptz NOT NULL,
  end_ts timestamptz NULL,
  duration_seconds int NULL,
  severity text NULL,
  evidence jsonb NULL
);

CREATE INDEX IF NOT EXISTS idx_weather_fault_daily_site_day ON weather_fault_daily(site_id, day);
