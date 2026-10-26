-- Checkpointed incremental FDD (W4b).
-- One checkpoint row per site, rule, equipment, and result scope. The scope is
-- every identity field except the data revision and the window. A claim bumps
-- the fence. Publish replaces bucket results and advances the checkpoint in
-- one transaction, and only for the fence that holds a live lease.

CREATE TABLE IF NOT EXISTS fdd_incremental_checkpoint (
  site_id text NOT NULL,
  rule_id text NOT NULL,
  equipment_id text NOT NULL,
  scope_digest text NOT NULL,
  scope_canonical text NOT NULL,
  -- NULL until the first publish.
  processed_revision bigint,
  fence bigint NOT NULL DEFAULT 0,
  lease_owner text,
  lease_until timestamptz,
  updated_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (site_id, rule_id, equipment_id, scope_digest),
  CONSTRAINT fdd_incremental_checkpoint_revision CHECK (processed_revision >= 0),
  CONSTRAINT fdd_incremental_checkpoint_fence CHECK (fence >= 0)
);

CREATE TABLE IF NOT EXISTS fdd_interval_result (
  site_id text NOT NULL,
  rule_id text NOT NULL,
  equipment_id text NOT NULL,
  scope_digest text NOT NULL,
  bucket_start timestamptz NOT NULL,
  bucket_end timestamptz NOT NULL,
  fault_seconds double precision NOT NULL,
  covered_seconds double precision NOT NULL,
  sample_count bigint NOT NULL,
  data_revision bigint NOT NULL,
  fence bigint NOT NULL,
  computed_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (site_id, rule_id, equipment_id, scope_digest, bucket_start),
  CONSTRAINT fdd_interval_result_bounds CHECK (bucket_end > bucket_start),
  CONSTRAINT fdd_interval_result_seconds CHECK (
    fault_seconds >= 0 AND covered_seconds >= 0 AND fault_seconds <= covered_seconds
  ),
  CONSTRAINT fdd_interval_result_samples CHECK (sample_count >= 0)
);
