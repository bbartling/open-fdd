---
title: Historian architecture
parent: Architecture
nav_order: 6
---

# Open-FDD historian architecture

> Status: implementation plan and storage contract. The canonical layout and configuration described here are being introduced incrementally; legacy local Parquet/Feather/JSONL paths remain readable until migration tooling and runtime cutover are complete.

## Architectural contract

**Parquet is the canonical durable Open-FDD historian format.**

**Arrow is the in-memory execution format.**

**DataFusion is the analytical SQL engine.**

**Feather / Arrow IPC is optional cache, export, or interoperability storage only and is non-canonical.**

Open-FDD must run the same logical historian on a small local Docker host and on object storage:

```text
BACnet / Modbus / MQTT / CSV / API
                |
                v
          Open-FDD ingest
                |
          Arrow RecordBatches
                |
       micro-batch + validate
                |
                v
      immutable Parquet parts
                |
      partition + compact
                |
       Storage abstraction
          /           \
     file://          s3://
       |                |
Docker/VM disk      S3-compatible
          \           /
            DataFusion
                |
             FDD SQL
```

Railway is a deployment target for the generic S3-compatible backend; it is not a storage-engine special case.

## Existing implementation audit

The repository already contains most of the right building blocks, but they currently form two different historian paths.

### Bulk CSV/package path

`fdd_store::ingest_building` validates a building package, parses each equipment CSV directly into an Arrow `RecordBatch`, writes Parquet, then records sidecar metadata. The current physical layout is:

```text
<OPENFDD_PARQUET_ROOT>/
  building=<building_id>/
    equipment=<equipment_id>/
      history.parquet
```

Weather is also materialized as Parquet where available. Timestamp parsing is strict: malformed timestamps are skipped rather than replaced with the current time or epoch zero. Categorical schedule/mode roles remain Arrow UTF-8 while the normal FDD role columns are numeric.

The CSV import bridge under `edge/src/csv_ingest/parquet_bridge.rs` writes an intermediate building package under `workspace/data/csv_buildings/` and then invokes `fdd_store` to populate the Parquet sidecar root.

### Live MQTT/driver path

Central MQTT ingest currently calls the edge historian facade. For each telemetry envelope it:

1. writes a one-row Feather shard under `workspace/data/feather_store/...`;
2. appends a wide JSON row to `workspace/data/historian/<subdir>/telemetry_pivot.jsonl`;
3. rewrites an Arrow IPC snapshot from the full JSONL history.

That is useful bench/interoperability behavior, but it is not a scalable canonical historian. In particular, the Feather path can produce one file per poll/envelope, and the JSONL→IPC snapshot path repeatedly rereads the full history.

### DataFusion query path

`fdd_sql::register_parquet_tree` currently registers `**/*.parquet` as a `history` table. Central analytics optionally narrows registration to one `building=<id>` directory. This works for the local sidecar layout but makes recursive local filesystem globbing the storage contract.

`fdd_sql::run_sql` currently calls `DataFrame::collect()` and converts every result row into an in-memory JSON vector. That is acceptable for bounded FDD/analytics queries but is unsafe as the generic interactive-query contract for a historian that may eventually approach 1 TB.

### Feather classification

Current Feather/IPC usage falls into these categories:

| Usage | Classification | Direction |
| --- | --- | --- |
| `edge/src/historian/feather_store.rs` one-row live shards | legacy/interoperability path | stop treating as durability-critical; canonical live persistence moves to Parquet micro-batches |
| equipment `history.feather` writes | optional cache/interchange | retain where APIs/tests still need it |
| `telemetry_pivot.arrow` snapshot | bench/cache artifact | non-canonical; no durability guarantee |
| CSV ingest batch hook used for Feather dual-write | optional interoperability | keep until consumers are audited/migrated |

No long-term durability guarantee should rely on Feather alone.

## Canonical storage URL

Open-FDD uses one provider-neutral setting:

```text
OPENFDD_STORAGE_URL=file:///data/openfdd
```

or:

```text
OPENFDD_STORAGE_URL=s3://openfdd-history
```

A plain filesystem path remains accepted for local backwards compatibility.

When `OPENFDD_STORAGE_URL` is not set, the compatibility layer recognizes the legacy `OPENFDD_PARQUET_ROOT`. Legacy layout is not silently reinterpreted as canonical layout; the migration tool will make that transition explicit.

### S3-compatible configuration

The generic application configuration is:

```text
OPENFDD_STORAGE_URL=s3://openfdd-history
OPENFDD_S3_ENDPOINT=https://...
OPENFDD_S3_REGION=...
OPENFDD_S3_ACCESS_KEY_ID=...
OPENFDD_S3_SECRET_ACCESS_KEY=...
```

Provider-specific variable names belong in deployment configuration, where they are mapped into these variables.

Secrets must never be returned by config/status APIs or written to logs.

## Canonical dataset layout

The initial layout is Hive-style monthly partitioning:

```text
history/
  building_id=BUILDING_100/
    equipment_id=AHU_1/
      year=2026/
        month=08/
          part-20260820T143000Z-<unique>.parquet

weather/
  building_id=BUILDING_100/
    year=2026/
      month=08/
        part-20260820T143000Z-<unique>.parquet
```

Initial partition keys are:

```text
history: building_id + equipment_id + year + month
weather: building_id + year + month
```

Day partitioning is deliberately not the default. It can be benchmarked later without changing FDD SQL semantics.

Partition values are validated and cannot contain path traversal, separators, NULs, or `=`.

Building/equipment/year/month are physical partition columns and should be exposed by DataFusion without forcing FDD rules to know filenames.

## Logical row schema

A history row retains:

```text
timestamp_utc
equipment_id (logical/partition identity)
canonical FDD role columns...
```

`timestamp_utc` remains a real Arrow timestamp. Malformed input is rejected/skipped according to the existing strict contracts; Open-FDD never invents a timestamp.

Partition columns should not be duplicated into every Parquet row unless a measured compatibility requirement justifies it.

## Append lifecycle

Parquet is immutable-oriented. The normal continuous write path is:

```text
incoming telemetry
       |
       v
validated Arrow rows
       |
       v
in-memory micro-batch
       |
  row threshold OR time threshold OR shutdown
       |
       v
complete Parquet part
       |
       v
crash-safe publish
```

Configuration:

```text
OPENFDD_PARQUET_FLUSH_ROWS=5000
OPENFDD_PARQUET_FLUSH_SECONDS=60
OPENFDD_PARQUET_TARGET_FILE_MB=128
```

The first implementation defaults are intentionally conservative for BAS polling. They are operator settings, not rule constants.

Local publication writes a temporary sibling file, flushes/closes it, and atomically renames it into the final partition where the filesystem supports normal atomic rename semantics.

Object storage builds a complete Parquet object and performs one upload. No code appends in-place to an existing Parquet object.

## Parquet writer policy

Writer configuration must be explicit. The initial direction is:

- Snappy compression for low CPU overhead on edge/VM hosts;
- Parquet statistics enabled;
- bounded row groups;
- immutable collision-safe part names.

Compression and row-group sizing should be benchmarked before more aggressive tuning. The goal is DataFusion pruning and predictable CPU rather than maximum compression ratio.

## Compaction lifecycle

Continuous telemetry must not create millions of tiny files.

Compaction operates one logical partition at a time:

```text
list small parts
     |
read bounded batches
     |
write replacement part
     |
validate schema + row count
     |
publish replacement
     |
only then delete obsolete parts
```

Configuration begins with:

```text
OPENFDD_PARQUET_TARGET_FILE_MB=128
OPENFDD_COMPACTION_MIN_FILES=8
OPENFDD_COMPACTION_ENABLED=true
```

Compaction may run concurrently with ingestion/FDD, but immutable input parts remain visible until the replacement is safely published. A running query must never depend on a partially written replacement.

## DataFusion integration

The long-term `history` registration target is the dataset root, not a recursive local glob.

DataFusion should expose Hive partition columns:

```text
building_id
equipment_id
year
month
```

Normal continuous FDD should issue explicit building/equipment/time predicates so partition pruning, column pruning, row-group statistics, and timestamp predicate pushdown restrict reads to a tiny fraction of retained history.

FDD SQL continues to refer to logical tables and role columns, not physical part files.

## Query safety and memory

A 1 TB historian does not imply 1 TB of RAM.

Configuration direction:

```text
OPENFDD_QUERY_MEMORY_MB=512
OPENFDD_DATAFUSION_SPILL_DIR=/workspace/.cache/datafusion-spill
OPENFDD_QUERY_MAX_ROWS=10000
```

Rule execution may retain its existing bounded result contracts. Generic/interactive SQL paths must not blindly materialize unlimited results into one JSON vector. Streaming, pagination, or a hard maximum response-row contract should be used depending on API semantics.

## Schema evolution

Safe evolution rules:

- adding a nullable role is allowed;
- missing optional roles remain nullable/NA;
- categorical roles remain UTF-8;
- an incompatible datatype for an existing canonical role fails clearly;
- no silent reinterpretation of a role datatype.

Old monthly partitions must remain queryable after nullable columns are added.

## Weather

Weather follows the same Parquet/storage philosophy under `weather/`. Existing fallback behavior that derives weather from weather-like `history` equipment remains supported so ECON/OAT rules do not regress during migration.

## Bulk analysis vs continuous AFDD

The historian architecture supports two explicit operating modes.

### Bulk analysis

```text
CSV/package -> Parquet -> requested analysis window -> DataFusion/FDD -> done
```

Importing historical data does **not** implicitly start a scheduler.

### Continuous AFDD

```text
live append -> Parquet micro-batches -> scheduler -> rolling window -> DataFusion/FDD
```

The scheduler interval and analysis lookback are independent. Initial configuration target:

```text
OPENFDD_AFDD_MODE=bulk|continuous
OPENFDD_AFDD_INTERVAL_MINUTES=60
OPENFDD_AFDD_LOOKBACK_VALUE=24
OPENFDD_AFDD_LOOKBACK_UNIT=hours
```

A continuous run determines its window end from the latest successfully persisted telemetry timestamp, not blindly from wall clock. Rolling windows intentionally overlap so late-arriving BAS data can be evaluated on a subsequent cycle.

The scheduler is decoupled from ingest: a successful Parquet flush does not synchronously run every FDD rule.

## Continuous finding/state principles

Rolling windows require stable finding continuity rather than duplicate findings every cycle. Existing finding contracts will be preserved while adding episode identity/continuation metadata where necessary (`first_seen`, `last_seen`, occurrence/run metadata, status).

Scheduler checkpoint state is small durable metadata separate from Parquet history. Restarts perform at most one due rolling-window catch-up rather than replaying every missed wall-clock tick. Duplicate concurrent cycles for the same scope are prevented.

## Railway deployment model

Railway's role is deployment wiring around the generic storage contract:

```text
openfdd-web (public domain)
      |
Railway private DNS
      |
openfdd-central (private)
      |
OPENFDD_STORAGE_URL=s3://<bucket>
      |
Railway Storage Bucket (private, S3-compatible)
```

Railway bucket credential variables are mapped to the generic `OPENFDD_S3_*` names. Application code must not inspect `RAILWAY_*` variables to decide historian behavior.

Small mutable application/session state may still use a Railway volume when appropriate, but the canonical BAS historian should be object storage once S3 mode is enabled. Container ephemeral disk is never the canonical cloud historian.

## Local Docker / VM model

A normal local install needs no object-storage service:

```text
OPENFDD_STORAGE_URL=file:///data/openfdd
```

with a Docker volume or host directory mounted at `/data/openfdd`.

An optional MinIO Compose recipe can exercise the same S3 code path locally; MinIO is test/advanced infrastructure, not a requirement for basic Open-FDD.

## Migration model

Legacy storage is migrated explicitly rather than silently rewritten.

The migration command will:

- discover legacy `building=<id>/equipment=<id>/history.parquet` and eligible Feather/CSV sources;
- preserve timestamps, equipment identity, and row counts;
- write canonical monthly immutable parts;
- report rows/files/bytes/errors;
- support dry-run;
- avoid overwriting already published canonical part names.

## Historian inspection

The operator stats command/API will report lightweight metadata such as:

```text
buildings
equipment
partitions
Parquet file count
total bytes
small-file count
median/largest file
oldest/newest timestamp
estimated rows
storage backend
```

Expensive full-dataset scans are not performed on every UI page load.

## Observability

Historian/AFDD logs and metrics should reuse the existing tracing/observability stack. Target counters/timers include ingest rows/bytes, flush count/duration, Parquet file count, compaction work, query duration/rows/bytes, AFDD cycle state, and data freshness.

Never log S3 secret credentials.

## Backup and restore

Local deployments back up the configured storage root plus the small mutable application/session state needed by the deployment.

Object-storage deployments use bucket durability/versioning/backup policy appropriate to the provider. A Railway environment has an isolated bucket instance; production backup policy must not assume a preview/staging bucket is the same object namespace.

## Scalability target

The architectural target is hundreds of GB to approximately 1 TB retained history without full-dataset memory materialization.

Scale comes from:

```text
monthly Hive partitions
building/equipment pruning
timestamp predicate pushdown
Parquet statistics
column pruning
bounded Arrow batches
immutable parts
small-file compaction
DataFusion spill/memory limits
object storage
rolling AFDD windows
```

The key continuous-mode benchmark is not “how fast can Open-FDD scan 1 TB?” It is “how little of the retained 1 TB does a normal building/time-window AFDD cycle need to touch?”

## Implementation phases

1. **Storage contract and audit** — generic storage URL/config, safe canonical paths, crash-safe local backend, this document.
2. **Partitioned Parquet writer** — immutable parts, micro-batches, explicit writer options, bulk/local migration path.
3. **DataFusion dataset registration** — logical dataset root, Hive partition pruning, query safeguards.
4. **Compaction** — bounded partition compactor and stats.
5. **S3-compatible backend** — generic object store, MinIO tests, Railway bucket mapping.
6. **Operator tooling** — migrate historian, stats/health API/CLI.
7. **Continuous AFDD** — scheduler/checkpoint, rolling windows, run-now/backfill, finding continuity, UI status/history.
8. **Scale benchmarks** — deterministic generators and measured reports.

Each phase must preserve existing FDD/weather behavior and pass the repository's normal CI/security/docs gates before the next runtime cutover.
