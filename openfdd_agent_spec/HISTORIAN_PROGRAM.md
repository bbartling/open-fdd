# Historian / Railway implementation program

Last updated: 2026-08-27

Canonical architecture: [`docs/HISTORIAN_ARCHITECTURE.md`](docs/HISTORIAN_ARCHITECTURE.md)  
Full audit/design: [`../docs/architecture/historian.md`](../docs/architecture/historian.md)

**Plan 4 (2026-08-27):** Feather / Arrow-IPC dual-write and `OPENFDD_LEGACY_INGEST_MIRROR` are **retired**. Canonical durability is Parquet under `OPENFDD_STORAGE_URL` only. App updates keep the same volume or S3 bucket — that is the restore path. H6 migrate CLI is **not** a product path (offline library helpers may remain in `fdd_store`; do not surface in `fdd_cli`).

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

- [x] PR #757 — `feat/partitioned-parquet-writer`, merged to `master` as `11df6089`
- [x] immutable collision-safe part names
- [x] UTC month split for RecordBatches
- [x] explicit Snappy compression + page statistics + bounded row groups
- [x] validate optional `building_id` / `equipment_id` batch identity against the trusted partition path
- [x] omit identity columns from physical Parquet so DataFusion can expose them exactly once as Hive partition columns
- [x] local crash-safe publish
- [x] append/month-boundary/round-trip/strict timestamp tests
- [x] bounded micro-batch accumulator with per-equipment schema consistency
- [x] row-threshold OR elapsed-time flush policy
- [x] failed-write buffering retained for explicit retry
- [x] clean shutdown drain through the same immutable writer

H2 merged only after the changed-head FDD engine, Rust stack, AppSec, docs, and security workflows were green.

### H3 — Logical DataFusion dataset registration + query safety

- [x] PR #758 — `feat/datafusion-historian-registration`, merged to `master` as `c5974abd`
- [x] register canonical local `history/` dataset root instead of making `**/*.parquet` the long-term contract
- [x] expose Hive partition columns (`building_id`, `equipment_id`, `year`, `month`); canonical partition values remain UTF-8 path literals (for example `year='2026'`, `month='08'`) so zero-padded month pruning is stable across DataFusion/local/object-store backends
- [x] preserve legacy sidecar fallback during migration
- [x] partition/date filter coverage plus physical-plan file pruning assertions
- [x] schema evolution coverage across mixed Parquet role columns
- [x] bounded interactive query collection plus Arrow streaming contract (`collect_sql_bounded`, `stream_sql`)
- [x] DataFusion memory/spill configuration wiring via H1 historian config; CLI query runtime uses the configured session
- [x] agent/build architecture docs updated for the H3 contract

H3 merged only after its exact changed head passed FDD engine, Rust stack, AppSec, docs, security, and review gates.

### H4 — Compaction

- [x] PR #760 — `feat/historian-compaction`, merged to `master` as `32eabc68`
- [x] identify small files partition-by-partition without crossing building/equipment/year/month boundaries
- [x] bounded-memory replacement writer streams Parquet batches instead of materializing a partition
- [x] nullable schema evolution is unioned safely; incompatible type changes fail closed
- [x] validate replacement row count/schema before changing the query surface
- [x] reject duplicate plan inputs and unsafe/non-canonical partition paths
- [x] retire source `.parquet` files to hidden tombstones, publish the validated replacement, fsync the partition directory, then delete retired sources
- [x] surface rollback failures and report cleanup-pending tombstones
- [x] lightweight serializable plan/result/summary metrics with distinct partition accounting
- [x] unit coverage for partition-local planning, row preservation, nullable schema evolution, duplicate inputs, summary accounting, and failure safety
- [x] local H4 compaction is offline-only; it is not scheduled from the product runtime and must not overlap DataFusion scans of the same local historian

The older stacked PR #759 remains closed historical context only. H4 merged only after exact-head FDD engine, Rust stack, AppSec, docs/security, and review gates were green.

### H5 — S3-compatible backend + Railway

- [x] PR #762 — `feat/s3-historian-backend`, merged to `master` as `9239574a`
- [x] direct generic `object_store` integration (same ecosystem used by DataFusion/Parquet)
- [x] AWS S3 / MinIO / Railway-compatible endpoint, region and credentials
- [x] virtual-hosted/path-style configuration for compatible providers
- [x] credential/session-token validation and redacted debug output; secrets are never logged
- [x] DataFusion object-store registration and canonical Hive partition exposure
- [x] building-scoped object discovery before DataFusion scans unrelated objects
- [x] central S3 scope-index refresh with fail-closed building presence checks
- [x] DataFusion historian tuning contract for Parquet filter pushdown/reordering, metadata hints, memory/spill, partition and batch controls
- [x] optional loopback-only local MinIO Compose recipe
- [x] Railway Storage Bucket mapping docs without Railway-specific engine branching
- [x] Railway central uses the bucket as canonical historian; container disk is scratch/spill only
- [x] deployment language is LAN/VPN/private-ingress only; H5 does not introduce a public historian or public central API

Railway mapping is deployment configuration, never Rust provider branching:

```text
OPENFDD_STORAGE_URL=s3://${{bucket.BUCKET}}
OPENFDD_S3_ENDPOINT=${{bucket.ENDPOINT}}
OPENFDD_S3_REGION=${{bucket.REGION}}
OPENFDD_S3_ACCESS_KEY_ID=${{bucket.ACCESS_KEY_ID}}
OPENFDD_S3_SECRET_ACCESS_KEY=${{bucket.SECRET_ACCESS_KEY}}
OPENFDD_S3_URL_STYLE=virtual
OPENFDD_S3_ALLOW_HTTP=false
```

Compatible providers may use path style instead. `OPENFDD_S3_ALLOW_HTTP=true` is limited to explicit local/test endpoints such as loopback MinIO. H5 merged only after its exact head passed FDD engine, Rust stack, AppSec, docs, security, and review gates.

### H6 — Migration + operator historian tooling

- [x] PR #764 — `feat/historian-migration-tooling`, merged to `master` as `d9705273`
- [x] recursively discover and classify legacy Parquet, JSONL/NDJSON, and Feather/Arrow IPC historian artifacts
- [x] require trusted `building=<id>/equipment=<id>` path identity; never invent identity from point IDs or defaults
- [x] reject unsafe/conflicting identity and non-canonical/ambiguous migration inputs
- [x] bounded streamed migration of eligible legacy `history.parquet` into canonical monthly parts
- [x] bounded JSONL scalar-schema conversion with strict timestamp parsing and mixed/nested type rejection
- [x] bounded Arrow IPC/Feather conversion with `timestamp` → `timestamp_utc` normalization and timestamp-type validation
- [x] use the same staging + atomic receipt + part hash verification protocol for every migrated format
- [x] restart-safe/idempotent reruns resume the exact publish plan; changed sources fail closed
- [x] row-count preservation plus first/last timestamp and equipment identity reports
- [x] footer-only local canonical historian stats: files, bytes, rows, partitions, buildings, equipment, month range, invalid layout, and H4-aligned small-file health
- [x] public serializable `HistorianStats` / migration report API (H6 library); product CLI `historian-dry-run` / `historian-migrate` / `historian-stats` **retired** (Plan 4 — not a cloud restore path)
- [x] S3 compatibility registration carry-forward is fail-closed when a building scope is absent; explicit global/operator registration remains separate

H6 remains offline/operator migration. It does not delete legacy data and does not make migration concurrent with live ingest. H6 merged only after PR #764's exact final head passed FDD, Rust stack, AppSec, docs/security workflows and had no review threads.

### H7 — Live ingest micro-batch cutover

- [x] PR #765 — `feat/live-historian-ingest-cutover`, merged to `master` as `07f59e98`
- [x] trace trustworthy building/equipment/role identity from fieldbus/MQTT metadata before mapping live points
- [x] no arbitrary parsing of BACnet/REST point IDs as canonical equipment roles
- [x] connect normalized live Arrow batches to the H2 `MicroBatchHistorian`
- [x] call elapsed-time flush from the owning central MQTT loop and drain the same micro-batcher on graceful Central shutdown
- [x] persist latest successfully persisted eligible telemetry timestamp at `state/live-historian/latest-telemetry.json` on the configured canonical backend for H8 restart/scheduler use
- [x] complete-object S3 live writer through the generic H5-compatible object-store contract; never fall back to ephemeral container disk
- [x] stop durability-critical dependence on JSONL/Arrow-IPC snapshot rewrite
- [x] Feather/JSONL MQTT mirror **retired** (Plan 4); was compatibility-only behind `OPENFDD_LEGACY_INGEST_MIRROR` — do not reintroduce
- [x] preserve bad/stale scalar point roles as nullable values without changing an equipment schema mid-batch

H7 uses explicit `OPENFDD_BUILDING_ID` plus configured device/point metadata at the fieldbus publisher. Missing building identity fails closed for canonical persistence; central does not infer building/equipment/role identity from transport IDs or topic strings. H7 merged only after PR #765's exact final head passed FDD, Rust stack, AppSec, docs/security workflows and had no unresolved review threads.

### H8 — Continuous AFDD scheduler / findings / API

- [x] explicit `bulk` vs `continuous` modes
- [x] interval independent from rolling lookback
- [x] rolling end time = latest successfully persisted eligible telemetry
- [x] overlapping rolling windows support late arrivals when lookback exceeds cadence
- [x] persisted scheduler checkpoint on the canonical local/S3 backend
- [x] no overlapping cycle for same scope
- [x] one restart catch-up when due, no missed-tick storm
- [x] run-now uses the same execution engine as scheduled cycles
- [x] explicit bounded historical backfill chunk planner
- [~] finding continuity/dedup preserves existing contracts; H8 does not fabricate first/last-seen fields when the current findings contract does not expose them
- [x] building/rule failure isolation remains in the registry engine and cycle status exposes succeeded/failed/skipped counts

Target configuration:

```text
OPENFDD_AFDD_MODE=bulk|continuous
OPENFDD_AFDD_INTERVAL_MINUTES=60
OPENFDD_AFDD_LOOKBACK_VALUE=24
OPENFDD_AFDD_LOOKBACK_UNIT=hours
```

H8 Central owns the continuous timer, reads the H7 persisted telemetry watermark, persists `state/afdd/scheduler-checkpoint.json`, serializes same-scope runs, and exposes authenticated scheduler status and run-now APIs.

### H9 — AFDD / historian / MQTT React operations UX

The operations page gains two additional radio-selectable configuration surfaces alongside the existing views: **AFDD Config** and **MQTT Config**. These are operator tools, not a public cloud console.

#### AFDD Config / Scheduler

- [x] radio/navigation entry for `AFDD Config`
- [x] scheduler widget with operating mode (`bulk` / `continuous`)
- [x] frequency and rolling lookback shown as separate concepts; deployment-owned values remain read-only when runtime mutation is not supported
- [x] last run / analyzed-through / latest historian sample / next run
- [x] persisted scheduler checkpoint and catch-up state
- [x] historian backend/size/files/small-files/compaction health surface reads Central data-management health and reports unavailable fields honestly rather than synthesizing values
- [x] run AFDD now through the same H8 execution engine used by scheduled cycles
- [x] recent AFDD cycles with success/partial/failure state
- [x] stale BAS data health independent of scheduler health using persisted telemetry freshness
- [x] finding first/last-seen and continuity fields are rendered when exposed by the current findings response; unavailable contract fields are explicitly identified rather than fabricated
- [x] deployment-backed values render read-only when runtime configuration cannot safely be changed from the UI; never show fake controls

#### MQTT Config / Test Monitor

- [x] radio/navigation entry for `MQTT Config`
- [x] AWS IoT Core test-client-style conceptual monitor layout without copying AWS branding or cloud assumptions
- [x] show broker connection state, client/runtime identity, subscriptions, and message counters without exposing credentials
- [x] topic-filter input supporting normal MQTT topic filters (`+` and `#`) with validation and local buffered-message matching
- [x] bounded live/recent message list with receive timestamp, topic, payload size, QoS/retain metadata
- [x] expandable payload viewer with pretty JSON when valid and safe text/hex fallback for non-JSON payloads
- [x] pause/resume display and clear-local-view actions that do not interrupt broker ingestion
- [x] bounded in-memory/server-side observation buffer; monitoring is not a second historian
- [x] reconnect/error events visible separately from telemetry messages
- [x] test publish remains disabled/read-only unless a future explicit backend capability/config flag enables it
- [x] because test publish is disabled in H9, no browser publish path bypasses authenticated operator controls, topic validation, payload limits, or audit requirements
- [x] browser never receives MQTT passwords, private keys, S3 secrets, or raw deployment credentials
- [x] MQTT monitor traffic is exposed through authenticated Central API plumbing rather than opening the broker directly to the browser

Follow-on (PR #779, Vite-gated before GHCR web):

- [x] Operations OT status strip (`/api/mqtt/monitor`, `/api/ingest/stats`, `/api/edges`)
- [x] MQTT listen poll default **1 s** (cell-aware slower options retained)
- [x] Sites inventory **Ingest** column CSV / MQTT / Both (labels only; not dual-writer historian)

H9 is gated on the exact final PR head passing frontend/Rust/security/docs workflows with zero unresolved review threads before merge.

### H10 — Scale benchmarks and release qualification

- [ ] deterministic synthetic historian generator
- [ ] equipment/day, equipment/month, building/hour, monthly aggregation, weather join, representative FDD
- [ ] continuous append + rolling AFDD workload
- [ ] report files/partitions/bytes/rows/time/memory and pruning where measurable
- [ ] scalable manual targets (1 GB / 10 GB / 100 GB / ~1 TB architecture validation)
- [ ] local Docker qualification
- [ ] optional MinIO qualification
- [ ] Railway `:nightly` qualification
- [ ] AFDD scheduler operations UX qualification
- [ ] MQTT monitor soak with bounded message buffer and payload rendering under sustained telemetry

## Non-negotiable gates

- Do not add a traditional database as canonical historian.
- Do not hard-code Railway in historian/FDD logic.
- Do not produce one Parquet file per telemetry sample.
- Do not reintroduce Feather/JSONL dual-write or treat Feather as durable restore (Plan 4 retired writers; restore = volume/`OPENFDD_STORAGE_URL`).
- Do not make bulk CSV import start recurring AFDD.
- Do not rescan retained history for every continuous AFDD cycle.
- Do not weaken auth/security or log S3/MQTT secrets.
- Do not expose MQTT broker credentials or private keys to the React client.
- Keep historian/central/MQTT ingress LAN/VPN/private-only; do not describe these services as public.
- Do not merge a phase until its changed-head CI and review threads are clean.
