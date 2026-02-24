-- Motor runtime cache for Grafana (data-model driven; empty = NO DATA)
CREATE TABLE IF NOT EXISTS analytics_motor_runtime (
    site_id text NOT NULL,
    period_start date NOT NULL,
    period_end date NOT NULL,
    runtime_hours double precision NOT NULL,
    point_external_id text,
    point_brick_type text,
    updated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (site_id, period_start, period_end)
);
