-- FDD run status: last run time and status for Grafana "Fault Runner" panel
CREATE TABLE IF NOT EXISTS fdd_run_log (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    run_ts timestamptz NOT NULL,
    status text NOT NULL DEFAULT 'ok',
    sites_processed int NOT NULL DEFAULT 0,
    faults_written int NOT NULL DEFAULT 0,
    error_message text
);

CREATE INDEX IF NOT EXISTS idx_fdd_run_log_run_ts ON fdd_run_log(run_ts DESC);
