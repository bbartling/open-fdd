-- Site data revision and the sample spans that moved it (W4a).
-- Forward-only. A revision advances when the sample writer returns a row
-- whose stored value differed, or when a sample row is removed.
-- Identical rows are not recorded. Count, sum, and max(ts) are not consulted.

CREATE TABLE IF NOT EXISTS data_revision (
  site_id text PRIMARY KEY,
  revision bigint NOT NULL,
  updated_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT data_revision_nonnegative CHECK (revision >= 0)
);

CREATE TABLE IF NOT EXISTS sample_changed_range (
  site_id text NOT NULL,
  openfdd_key text NOT NULL,
  revision bigint NOT NULL,
  range_start timestamptz NOT NULL,
  range_end timestamptz NOT NULL,
  change_kind text NOT NULL,
  PRIMARY KEY (site_id, revision, openfdd_key, change_kind),
  CONSTRAINT sample_changed_range_bounds CHECK (range_end >= range_start),
  CONSTRAINT sample_changed_range_kind CHECK (change_kind IN ('upsert', 'removed'))
);

CREATE INDEX IF NOT EXISTS sample_changed_range_site_rev_idx
  ON sample_changed_range (site_id, revision);
