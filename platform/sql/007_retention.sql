-- Data retention: drop hypertable chunks older than the configured interval.
-- Default 365 days; override at bootstrap with --retention-days N or OFDD_RETENTION_DAYS in platform/.env.

-- timeseries_readings: BACnet, weather telemetry
SELECT add_retention_policy('timeseries_readings', drop_after => INTERVAL '365 days', if_not_exists => true);

-- fault_results: FDD flags
SELECT add_retention_policy('fault_results', drop_after => INTERVAL '365 days', if_not_exists => true);

-- host_metrics, container_metrics: System Resources dashboard (may not exist if 006 skipped)
DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM timescaledb_information.hypertables WHERE hypertable_name = 'host_metrics') THEN
    PERFORM add_retention_policy('host_metrics', drop_after => INTERVAL '365 days', if_not_exists => true);
  END IF;
  IF EXISTS (SELECT 1 FROM timescaledb_information.hypertables WHERE hypertable_name = 'container_metrics') THEN
    PERFORM add_retention_policy('container_metrics', drop_after => INTERVAL '365 days', if_not_exists => true);
  END IF;
END $$;
