"""Apply disposable Postgres schema slices for C3 SQL-QUAL DB benches (harness-only)."""

from __future__ import annotations

MINIMAL_SI_CUTOVER_FIXTURE_DDL = """
CREATE TABLE IF NOT EXISTS site (
  site_id text PRIMARY KEY,
  dis text,
  timezone text NOT NULL DEFAULT 'UTC',
  enabled boolean NOT NULL DEFAULT true,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS point_map (
  site_id text NOT NULL REFERENCES site(site_id),
  openfdd_key text NOT NULL,
  haystack_id text NOT NULL,
  role text,
  unit text,
  equipment_id text,
  source_unit text,
  quantity text,
  si_cutover_exclude boolean NOT NULL DEFAULT false,
  PRIMARY KEY (site_id, openfdd_key)
);

CREATE TABLE IF NOT EXISTS sample (
  ts timestamptz NOT NULL,
  site_id text NOT NULL,
  openfdd_key text NOT NULL,
  haystack_id text,
  val double precision,
  unit text,
  quality text,
  PRIMARY KEY (site_id, openfdd_key, ts)
);

CREATE INDEX IF NOT EXISTS sample_site_key_ts_idx
  ON sample (site_id, openfdd_key, ts DESC);

CREATE TABLE IF NOT EXISTS unit_migration (
  site_id text NOT NULL,
  openfdd_key text NOT NULL,
  from_unit text NOT NULL,
  to_unit text NOT NULL,
  row_count bigint NOT NULL CHECK (row_count >= 0),
  started_at timestamptz NOT NULL,
  finished_at timestamptz NOT NULL,
  checksum text NOT NULL,
  PRIMARY KEY (site_id, openfdd_key, checksum)
);
"""


def apply_si_cutover_fixture_schema(cur) -> None:
    """Minimal plain-Postgres tables for 12A harness (no Timescale extension)."""
    for stmt in MINIMAL_SI_CUTOVER_FIXTURE_DDL.split(";"):
        sql = stmt.strip()
        if sql:
            cur.execute(sql)
