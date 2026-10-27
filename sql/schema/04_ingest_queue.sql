-- Wave-NF N8 shared ingest queue.
-- Logical identity matches the N5 hourly job key so Wave-B can insert durable
-- per-device windows into this table without a second queue.
--
-- JobKey = tenant + canonical_site + provider_instance + device
--        + model_revision + logical_window_start + logical_window_end + shard

CREATE TABLE IF NOT EXISTS ingest_job (
  job_id text PRIMARY KEY,
  tenant_id text NOT NULL,
  canonical_site text NOT NULL,
  provider_instance_id text NOT NULL,
  device_id text NOT NULL,
  model_revision text NOT NULL,
  logical_window_start timestamptz NOT NULL,
  logical_window_end timestamptz NOT NULL,
  shard text NOT NULL DEFAULT '',
  state text NOT NULL,
  attempt integer NOT NULL DEFAULT 0,
  not_before timestamptz NOT NULL,
  lease_owner text,
  lease_expiry timestamptz,
  fencing_token bigint NOT NULL DEFAULT 0,
  requested_points_digest text,
  estimated_cost integer NOT NULL DEFAULT 1,
  fetched_count integer NOT NULL DEFAULT 0,
  accepted_count integer NOT NULL DEFAULT 0,
  rejected_count integer NOT NULL DEFAULT 0,
  inserted_count integer NOT NULL DEFAULT 0,
  updated_count integer NOT NULL DEFAULT 0,
  unchanged_count integer NOT NULL DEFAULT 0,
  safe_error_code text,
  receipt_id text,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT ingest_job_state_chk CHECK (
    state IN (
      'queued',
      'leased',
      'retry_wait',
      'committed',
      'partial',
      'permanent_failure',
      'cancelled'
    )
  ),
  CONSTRAINT ingest_job_logical_key UNIQUE (
    tenant_id,
    canonical_site,
    provider_instance_id,
    device_id,
    model_revision,
    logical_window_start,
    logical_window_end,
    shard
  )
);

CREATE INDEX IF NOT EXISTS ingest_job_ready_idx
  ON ingest_job (state, not_before, logical_window_start, job_id);

CREATE INDEX IF NOT EXISTS ingest_job_portal_lease_idx
  ON ingest_job (provider_instance_id, state, lease_expiry);

CREATE INDEX IF NOT EXISTS ingest_job_site_idx
  ON ingest_job (canonical_site, logical_window_start DESC);

CREATE TABLE IF NOT EXISTS ingest_receipt (
  receipt_id text PRIMARY KEY,
  job_id text NOT NULL,
  tenant_id text NOT NULL,
  canonical_site text NOT NULL,
  provider_instance_id text NOT NULL DEFAULT '',
  device_id text NOT NULL DEFAULT '',
  model_revision text NOT NULL DEFAULT '',
  fencing_token bigint NOT NULL,
  committed_at timestamptz NOT NULL,
  counts jsonb NOT NULL,
  safe_error_code text
);

ALTER TABLE ingest_receipt ADD COLUMN IF NOT EXISTS provider_instance_id text NOT NULL DEFAULT '';
ALTER TABLE ingest_receipt ADD COLUMN IF NOT EXISTS device_id text NOT NULL DEFAULT '';
ALTER TABLE ingest_receipt ADD COLUMN IF NOT EXISTS model_revision text NOT NULL DEFAULT '';

-- Nullable server request id. Existing rows stay null. Old writers omit the column.
ALTER TABLE ingest_job ADD COLUMN IF NOT EXISTS server_request_id text;
ALTER TABLE ingest_receipt ADD COLUMN IF NOT EXISTS server_request_id text;

CREATE INDEX IF NOT EXISTS ingest_receipt_site_idx
  ON ingest_receipt (canonical_site, committed_at DESC);

CREATE TABLE IF NOT EXISTS ingest_scheduler_lease (
  lease_name text PRIMARY KEY,
  owner text NOT NULL,
  fencing_token bigint NOT NULL,
  expires_at timestamptz NOT NULL
);

CREATE TABLE IF NOT EXISTS ingest_portal_budget (
  provider_instance_id text PRIMARY KEY,
  max_in_flight integer NOT NULL,
  max_per_minute integer NOT NULL,
  tokens_remaining integer NOT NULL,
  window_start timestamptz NOT NULL,
  paused_until timestamptz,
  cap_override integer
);

-- One client key may be reused by different actors or tenants. The row is
-- unique for actor + tenant + action + client key, and stores the object and
-- payload hash from the request that reserved it.
CREATE TABLE IF NOT EXISTS ingest_idempotency (
  idempotency_key text NOT NULL,
  actor text NOT NULL,
  tenant_id text NOT NULL,
  action text NOT NULL,
  object_id text NOT NULL,
  payload_hash text NOT NULL,
  job_ids jsonb NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (actor, tenant_id, action, idempotency_key)
);

ALTER TABLE ingest_idempotency ADD COLUMN IF NOT EXISTS tenant_id text;
ALTER TABLE ingest_idempotency ADD COLUMN IF NOT EXISTS object_id text;
ALTER TABLE ingest_idempotency ADD COLUMN IF NOT EXISTS payload_hash text;

CREATE TABLE IF NOT EXISTS ingest_audit (
  audit_id bigserial PRIMARY KEY,
  at timestamptz NOT NULL DEFAULT now(),
  actor text NOT NULL,
  action text NOT NULL,
  job_id text,
  idempotency_key text,
  detail jsonb NOT NULL DEFAULT '{}'::jsonb
);

-- Coverage is derived queue state. These statements do not read or rewrite
-- historian samples. Existing jobs stay `not_assessed` until a worker
-- reconciles them.
ALTER TABLE ingest_job ADD COLUMN IF NOT EXISTS coverage text NOT NULL DEFAULT 'not_assessed';
ALTER TABLE ingest_receipt ADD COLUMN IF NOT EXISTS coverage text NOT NULL DEFAULT 'not_assessed';

CREATE TABLE IF NOT EXISTS ingest_point_coverage (
  job_id text NOT NULL,
  point_id text NOT NULL,
  disposition text NOT NULL,
  expected_slots integer NOT NULL,
  observed_slots integer NOT NULL,
  late_slots integer NOT NULL DEFAULT 0,
  PRIMARY KEY (job_id, point_id)
);

-- Idempotent apply ledger for one device window. A replay of the same
-- point and timestamp does not replace the first value.
CREATE TABLE IF NOT EXISTS ingest_applied_sample (
  tenant_id text NOT NULL,
  canonical_site text NOT NULL,
  provider_instance_id text NOT NULL,
  device_id text NOT NULL,
  model_revision text NOT NULL,
  point_id text NOT NULL,
  ts timestamptz NOT NULL,
  value_bits text NOT NULL,
  first_job_id text NOT NULL,
  PRIMARY KEY (
    tenant_id, canonical_site, provider_instance_id, device_id, model_revision, point_id, ts
  )
);

-- Retention scan for the replay ledger.
CREATE INDEX IF NOT EXISTS ingest_applied_sample_site_ts_idx
  ON ingest_applied_sample (tenant_id, canonical_site, ts);

-- Replay horizon per tenant and site. Ledger rows before pruned_before may be
-- gone, so a retry or backfill of a window that starts earlier is refused.
-- pruned_before only moves forward.
CREATE TABLE IF NOT EXISTS ingest_applied_sample_horizon (
  tenant_id text NOT NULL,
  canonical_site text NOT NULL,
  pruned_before timestamptz,
  updated_at timestamptz NOT NULL,
  PRIMARY KEY (tenant_id, canonical_site)
);

-- Verified-coverage cursor per device and committed model revision.
-- verified_through only moves forward. The hole columns name the first
-- instant that is not covered by committed windows, when there is one.
CREATE TABLE IF NOT EXISTS ingest_coverage_cursor (
  tenant_id text NOT NULL,
  canonical_site text NOT NULL,
  provider_instance_id text NOT NULL,
  device_id text NOT NULL,
  model_revision text NOT NULL,
  verified_through timestamptz NOT NULL,
  hole_at timestamptz,
  hole_state text,
  hole_code text,
  updated_at timestamptz NOT NULL,
  PRIMARY KEY (tenant_id, canonical_site, provider_instance_id, device_id, model_revision),
  CONSTRAINT ingest_coverage_cursor_hole_chk CHECK (
    (hole_at IS NULL AND hole_state IS NULL AND hole_code IS NULL)
    OR (hole_at IS NOT NULL AND hole_state IS NOT NULL AND hole_at >= verified_through)
  )
);
