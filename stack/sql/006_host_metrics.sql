-- Host and container resource metrics for IoT/IT monitoring
-- Scraper (run_host_stats.py) writes here; Grafana dashboards query it.

CREATE TABLE IF NOT EXISTS host_metrics (
    ts timestamptz NOT NULL,
    hostname text NOT NULL,
    mem_total_bytes bigint NOT NULL,
    mem_used_bytes bigint NOT NULL,
    mem_available_bytes bigint NOT NULL,
    swap_total_bytes bigint NOT NULL,
    swap_used_bytes bigint NOT NULL,
    load_1 float NOT NULL,
    load_5 float NOT NULL,
    load_15 float NOT NULL
);

SELECT create_hypertable('host_metrics', 'ts', if_not_exists => TRUE);
CREATE INDEX IF NOT EXISTS idx_host_metrics_host ON host_metrics (hostname, ts DESC);

CREATE TABLE IF NOT EXISTS container_metrics (
    ts timestamptz NOT NULL,
    container_name text NOT NULL,
    cpu_pct float NOT NULL,
    mem_usage_bytes bigint NOT NULL,
    mem_limit_bytes bigint,
    mem_pct float,
    pids int NOT NULL,
    net_rx_bytes bigint,
    net_tx_bytes bigint,
    block_read_bytes bigint,
    block_write_bytes bigint
);

SELECT create_hypertable('container_metrics', 'ts', if_not_exists => TRUE);
CREATE INDEX IF NOT EXISTS idx_container_metrics_name ON container_metrics (container_name, ts DESC);
