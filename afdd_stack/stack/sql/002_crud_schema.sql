-- Extended schema for open-fdd CRUD app
-- Sites, ingest jobs, points (Brick-style), timeseries, faults

-- Sites (buildings/facilities)
CREATE TABLE IF NOT EXISTS sites (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    name text NOT NULL,
    description text,
    metadata jsonb DEFAULT '{}',
    created_at timestamptz NOT NULL DEFAULT now()
);

-- Ingest jobs (each CSV upload = one job)
CREATE TABLE IF NOT EXISTS ingest_jobs (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    site_id uuid NOT NULL REFERENCES sites(id) ON DELETE CASCADE,
    name text,
    format text NOT NULL CHECK (format IN ('wide', 'long')),
    point_columns text[],
    row_count int NOT NULL DEFAULT 0,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_ingest_jobs_site ON ingest_jobs(site_id);

-- Points (Brick-style; links to timeseries storage)
CREATE TABLE IF NOT EXISTS points (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    site_id uuid NOT NULL REFERENCES sites(id) ON DELETE CASCADE,
    external_id text NOT NULL,
    brick_type text,
    unit text,
    description text,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE(site_id, external_id)
);

CREATE INDEX IF NOT EXISTS idx_points_site ON points(site_id);
CREATE INDEX IF NOT EXISTS idx_points_external ON points(site_id, external_id);

-- Timeseries readings (generic EAV; hypertable)
CREATE TABLE IF NOT EXISTS timeseries_readings (
    ts timestamptz NOT NULL,
    site_id text NOT NULL,
    point_id uuid NOT NULL REFERENCES points(id) ON DELETE CASCADE,
    value double precision,
    job_id uuid REFERENCES ingest_jobs(id) ON DELETE SET NULL
);

SELECT create_hypertable('timeseries_readings', 'ts', if_not_exists => TRUE);
CREATE INDEX IF NOT EXISTS idx_ts_readings_site_pt ON timeseries_readings(site_id, point_id);

-- Fault results (canonical FDD schema: ts, site_id, equipment_id, fault_id, flag_value, evidence)
CREATE TABLE IF NOT EXISTS fault_results (
    ts timestamptz NOT NULL,
    site_id text NOT NULL,
    equipment_id text NOT NULL DEFAULT '',
    fault_id text NOT NULL,
    flag_value int NOT NULL DEFAULT 1,
    evidence jsonb
);

SELECT create_hypertable('fault_results', 'ts', if_not_exists => TRUE);
CREATE INDEX IF NOT EXISTS idx_fault_results_site ON fault_results(site_id);
CREATE INDEX IF NOT EXISTS idx_fault_results_equipment ON fault_results(site_id, equipment_id);

-- Fault events (start/end for Grafana annotations)
CREATE TABLE IF NOT EXISTS fault_events (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    site_id text NOT NULL,
    equipment_id text NOT NULL DEFAULT '',
    fault_id text NOT NULL,
    start_ts timestamptz NOT NULL,
    end_ts timestamptz,
    duration_seconds int,
    evidence jsonb
);

CREATE INDEX IF NOT EXISTS idx_fault_events_site ON fault_events(site_id);
CREATE INDEX IF NOT EXISTS idx_fault_events_equipment ON fault_events(site_id, equipment_id);
