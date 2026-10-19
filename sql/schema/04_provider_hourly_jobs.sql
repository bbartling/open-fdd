-- N5 durable per-device completed-hour ingest jobs.
-- History reads stay GET /api/v1/point/data. This schema does not call the portal.
-- NF update-log (GET /api/v1/point/updates/data) is not a cursor here: lab key returned 403.
-- Runtime also applies this DDL so existing volumes pick it up (initdb runs once).

CREATE TABLE IF NOT EXISTS provider_hourly_job (
  job_id text PRIMARY KEY,
  tenant text NOT NULL,
  canonical_site text NOT NULL,
  provider_instance text NOT NULL,
  device_id text NOT NULL,
  model_revision text NOT NULL,
  window_start timestamptz NOT NULL,
  window_end timestamptz NOT NULL,
  shard integer NOT NULL,
  shard_count integer NOT NULL,
  purpose text NOT NULL,
  generation bigint NOT NULL,
  state text NOT NULL,
  attempt integer NOT NULL DEFAULT 0,
  not_before timestamptz,
  lease_owner text,
  lease_expiry timestamptz,
  fencing_token bigint NOT NULL DEFAULT 0,
  point_ids jsonb NOT NULL,
  fetched_count integer NOT NULL DEFAULT 0,
  accepted_count integer NOT NULL DEFAULT 0,
  rejected_count integer NOT NULL DEFAULT 0,
  overlap_count integer NOT NULL DEFAULT 0,
  writer_acknowledged integer NOT NULL DEFAULT 0,
  received_at timestamptz,
  committed_at timestamptz,
  safe_error_code text,
  receipt_id text,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (
    tenant, canonical_site, provider_instance, device_id, model_revision,
    window_start, window_end, shard, purpose, generation
  )
);

CREATE INDEX IF NOT EXISTS provider_hourly_job_ready_idx
  ON provider_hourly_job (canonical_site, state, window_start);

CREATE TABLE IF NOT EXISTS provider_hourly_checkpoint (
  tenant text NOT NULL,
  canonical_site text NOT NULL,
  provider_instance text NOT NULL,
  device_id text NOT NULL,
  model_revision text NOT NULL,
  contiguous_end timestamptz NOT NULL,
  updated_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (tenant, canonical_site, provider_instance, device_id, model_revision)
);

CREATE TABLE IF NOT EXISTS provider_hourly_receipt (
  receipt_id text PRIMARY KEY,
  job_id text NOT NULL,
  outcome text NOT NULL,
  fetched_count integer NOT NULL,
  accepted_count integer NOT NULL,
  rejected_count integer NOT NULL,
  overlap_count integer NOT NULL,
  writer_acknowledged integer NOT NULL,
  safe_code text NOT NULL,
  series_facts jsonb NOT NULL DEFAULT '[]'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now()
);

ALTER TABLE provider_hourly_receipt
  ADD COLUMN IF NOT EXISTS series_facts jsonb NOT NULL DEFAULT '[]'::jsonb;

CREATE TABLE IF NOT EXISTS provider_hourly_gap (
  gap_id text PRIMARY KEY,
  tenant text NOT NULL,
  canonical_site text NOT NULL,
  provider_instance text NOT NULL,
  device_id text NOT NULL,
  model_revision text NOT NULL,
  window_start timestamptz NOT NULL,
  window_end timestamptz NOT NULL,
  reason text NOT NULL,
  recoverability text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (
    tenant, canonical_site, provider_instance, device_id, model_revision,
    window_start, window_end, reason
  )
);
