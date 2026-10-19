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
  fencing_token bigint NOT NULL,
  committed_at timestamptz NOT NULL,
  counts jsonb NOT NULL,
  safe_error_code text
);

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

CREATE TABLE IF NOT EXISTS ingest_idempotency (
  idempotency_key text PRIMARY KEY,
  actor text NOT NULL,
  action text NOT NULL,
  job_ids jsonb NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS ingest_audit (
  audit_id bigserial PRIMARY KEY,
  at timestamptz NOT NULL DEFAULT now(),
  actor text NOT NULL,
  action text NOT NULL,
  job_id text,
  idempotency_key text,
  detail jsonb NOT NULL DEFAULT '{}'::jsonb
);
