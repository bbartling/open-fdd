# Historian / Railway implementation program

Last updated: 2026-08-20

Canonical architecture: [`docs/HISTORIAN_ARCHITECTURE.md`](docs/HISTORIAN_ARCHITECTURE.md)  
Full audit/design: [`../docs/architecture/historian.md`](../docs/architecture/historian.md)

Legend: `[x]` merged/complete · `[~]` active/partial · `[ ]` not yet merged

## Goal

One Open-FDD application, same FDD SQL and logical historian:

```text
small PC / IT VM                  Railway / cloud
        |                               |
 file:///data/openfdd              s3://<bucket>
        |                               |
        +-------- Parquet dataset ------+
                         |
                    DataFusion
                         |
                      FDD SQL
```

The retained historian may grow toward ~1 TB, while ordinary AFDD cycles query only relevant building/equipment/month/time windows.

## Phase ledger

### H1 — Storage contract + architecture audit

- [x] PR #756 — `feat/parquet-object-historian-foundation`, merged to `master` as `6d75b50e`
- [x] generic `OPENFDD_STORAGE_URL` (`file://`, plain local path, `s3://`)
- [x] canonical monthly Hive partition paths
- [x] crash-safe local backend and path-traversal guards
- [x] historian architecture audit/documentation
- [x] `.env.example` configuration seed
- [x] agent architecture lock

H1 merged only after its changed-head FDD, Rust stack, AppSec, docs, and security CI were green.

### H2 — Immutable partitioned Parquet writer

- [~] PR #757 — `feat/partitioned-parquet-writer`, cleanly based on merged H1 / current `master`
- [~] immutable collision-safe part names
- [~] UTC month split for RecordBatches
- [~] explicit Snappy compression + page statistics + bounded row groups
- [~] local crash-safe publish
- [~] append/month-boundary/round-trip/strict timestamp tests
- [~] bounded micro-batch accumulator with per-equipment schema consistency
- [~] row-threshold OR elapsed-time flush policy
- [~] failed-write buffering retained for explicit retry
- [~] clean shutdown drain through the same immutable writer

### H3 — Logical DataFusion dataset registration + query safety

- [ ] register canonical dataset root instead of making `**/*.parquet` the long-term contract
- [ ] expose Hive partition columns (`building_id`, `equipment_id`, `year`, `month`)
- [ ] preserve legacy sidecar fallback during migration
- [ ] partition/date pruning tests
- [ ] schema evolution tests
- [ ] generic interactive query row safeguard / streaming contract
- [ ] DataFusion memory/spill configuration wiring

### H4 — Compaction

- [ ] identify small files partition-by-partition
- [ ] bounded-memory replacement writer
- [ ] publish/validate replacement before deleting inputs
- [ ] no row loss / schema preservation / failure-safety tests
- [ ] lightweight compaction metrics/stats

### H5 — S3-compatible backend + Railway

- [ ] direct generic `object_store` integration (same ecosystem used by DataFusion/Parquet)
- [ ] AWS S3 / MinIO / Railway-compatible endpoint, region and credentials
- [ ] virtual-hosted/path-style configuration for compatible providers
- [ ] never log credentials
- [ ] DataFusion object-store registration
- [ ] optional local MinIO Compose recipe
- [ ] Railway Storage Bucket mapping docs
- [ ] Railway central uses bucket as canonical historian; container disk is scratch
- [ ] Railway web remains the only public service in the minimal dashboard recipe

Railway mapping target (deployment config, never Rust provider branching):

```text
OPENFDD_STORAGE_URL=s3://${{bucket.BUCKET}}
OPENFDD_S3_ENDPOINT=${{bucket.ENDPOINT}}
OPENFDD_S3_REGION=${{bucket.REGION}}
OPENFDD_S3_ACCESS_KEY_ID=${{bucket.ACCESS_KEY_ID}}
OPENFDD_S3_SECRET_ACCESS_KEY=${{bucket.SECRET_ACCESS_KEY}}
```

Current Railway Storage Buckets are private S3-compatible buckets; current Railway docs use `BUCKET`, `ENDPOINT`, `REGION`, `ACCESS_KEY_ID`, and `SECRET_ACCESS_KEY`. New buckets use virtual-hosted-style URLs by default; support should remain generic because older/other S3-compatible endpoints may use path style.

### H6 — Migration + operator historian tooling

- [ ] migrate legacy `building=<id>/equipment=<id>/history.parquet`
- [ ] classify/migrate eligible legacy JSONL/Feather data without inventing identity
- [ ] dry-run and restart-safe behavior
- [ ] row/timestamp/equipment preservation report
- [ ] historian stats JSON/operator command/API

### H7 — Live ingest micro-batch cutover

- [ ] trace trustworthy equipment/role identity from fieldbus/MQTT metadata before mapping live points
- [ ] no arbitrary parsing of point IDs as canonical equipment roles
- [ ] connect normalized live Arrow batches to the H2 micro-batch primitive
- [ ] call elapsed-time flush from the owning runtime loop and shutdown drain on graceful exit
- [ ] latest successfully persisted telemetry timestamp
- [ ] stop durability-critical dependence on JSONL/Arrow-IPC snapshot rewrite
- [ ] Feather remains optional compatibility/interchange only

### H8 — Continuous AFDD scheduler / findings / API

- [ ] explicit `bulk` vs `continuous` modes
- [ ] interval independent from rolling lookback
- [ ] rolling end time = latest successfully persisted eligible telemetry
- [ ] overlapping windows for late arrivals
- [ ] persisted scheduler checkpoint
- [ ] no overlapping cycle for same scope
- [ ] one restart catch-up when due, no missed-tick storm
- [ ] run-now uses same engine
- [ ] explicit chunked historical backfill
- [ ] finding continuity/dedup preserves existing contracts
- [ ] building/rule failure isolation where safe

Target configuration:

```text
OPENFDD_AFDD_MODE=bulk|continuous
OPENFDD_AFDD_INTERVAL_MINUTES=60
OPENFDD_AFDD_LOOKBACK_VALUE=24
OPENFDD_AFDD_LOOKBACK_UNIT=hours
```

### H9 — AFDD / historian React operations UX

- [ ] operating-mode status
- [ ] frequency vs lookback visibly distinct
- [ ] last run / analyzed-through / latest historian sample / next run
- [ ] historian backend/size/files/small-files/compaction health
- [ ] run AFDD now
- [ ] recent AFDD cycles
- [ ] stale BAS data health independent of scheduler health
- [ ] finding first/last seen and continuity fields
- [ ] no fake runtime controls when deployment configuration is read-only

### H10 — Scale benchmarks and release qualification

- [ ] deterministic synthetic historian generator
- [ ] equipment/day, equipment/month, building/hour, monthly aggregation, weather join, representative FDD
- [ ] continuous append + rolling AFDD workload
- [ ] report files/partitions/bytes/rows/time/memory and pruning where measurable
- [ ] scalable manual targets (1 GB / 10 GB / 100 GB / ~1 TB architecture validation)
- [ ] local Docker qualification
- [ ] optional MinIO qualification
- [ ] Railway `:nightly` qualification

## Non-negotiable gates

- Do not add a traditional database as canonical historian.
- Do not hard-code Railway in historian/FDD logic.
- Do not produce one Parquet file per telemetry sample.
- Do not delete legacy Feather/JSONL paths before their consumers and migration needs are audited.
- Do not make bulk CSV import start recurring AFDD.
- Do not rescan retained history for every continuous AFDD cycle.
- Do not weaken auth/security or log S3 secrets.
- Do not merge a phase until its changed-head CI and review threads are clean.
