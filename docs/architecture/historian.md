---
title: Historian architecture
parent: Architecture
nav_order: 6
---

# Open-FDD historian architecture

> Status: H1–H4 are merged. The canonical local Parquet contract, immutable micro-batch writer, DataFusion registration/query safeguards, and offline local compactor are implemented. H5 adds the S3-compatible backend and cloud runtime wiring; legacy Parquet/Feather/JSONL paths remain readable until H6/H7 migration and live-ingest cutover are complete.

## Architectural contract

**Parquet is the canonical durable Open-FDD historian format.**

**Arrow is the in-memory execution format.**

**DataFusion is the analytical SQL engine.**

**Feather / Arrow IPC is optional cache, export, or interoperability storage only and is non-canonical.**

Open-FDD uses the same logical historian on a small local Docker/VM host and on object storage:

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

## Current implementation

### Canonical local storage

`OPENFDD_STORAGE_URL` is the provider-neutral historian setting. H1 supports local storage:

```text
OPENFDD_STORAGE_URL=file:///data/openfdd
```

The `s3://` form is the H5 target and is not available until the H5 object-store backend and runtime cutover land.

A plain filesystem path is accepted for local backwards compatibility. If the canonical setting is absent, `OPENFDD_PARQUET_ROOT` is recognized as a legacy compatibility path; legacy physical layout is never silently relabeled as canonical layout.

H1 also provides safe partition-value validation, local atomic publication, and historian resource settings.

### Immutable Parquet write path

H2 writes complete immutable Parquet parts under canonical UTC monthly Hive partitions. A batch may cross a calendar month; rows are split before publication. Optional `building_id` and `equipment_id` columns must match the trusted partition identity and are omitted from the physical payload so DataFusion exposes each identity exactly once from Hive partition metadata.

The normal micro-batch flush policy is rows **or** elapsed time **or** clean shutdown. Failed writes retain their buffered rows for explicit retry. Parts use collision-safe names, Snappy compression, statistics, and bounded row groups.

### DataFusion query path

H3 registers the canonical local `history/` dataset root rather than making recursive `**/*.parquet` globbing the long-term contract. DataFusion exposes Hive partition columns:

```text
building_id
equipment_id
year
month
```

Partition values remain UTF-8 path literals; use zero-padded filters such as `year = '2026'` and `month = '08'`. H3 tests assert physical-plan pruning so unrelated building/equipment/month files are absent from selected scans.

Legacy recursive Parquet remains a fallback only while H6 migration is incomplete.

H3 also provides:

- `collect_sql_bounded(ctx, sql, max_rows)` for bounded interactive materialization;
- `stream_sql(ctx, sql)` for Arrow record-batch streaming;
- DataFusion memory-pool and optional spill-directory configuration;
- schema-evolution coverage for nullable role additions and fail-closed incompatible datatypes.

### Local compaction

H4 (`#760`, merged as `32eabc68`) compacts small files within one canonical building/equipment/year/month partition using bounded memory. It validates replacement row count and logical schema before changing the query surface, rejects duplicate/unsafe inputs, surfaces rollback failures, and reports cleanup-pending tombstones.

The local cutover sequence is:

```text
list small source parts
        |
read bounded batches
        |
write hidden replacement candidate
        |
validate schema + row count
        |
retire source .parquet files to hidden tombstones
        |
publish validated replacement
        |
fsync partition directory
        |
delete retired tombstones
```

**H4 compaction is offline-only.** It must not overlap DataFusion scans of the same local historian. Local filesystems do not provide an atomic transaction that exchanges an arbitrary set of source files for one replacement: publishing first creates a duplicate-row window, while retiring first creates a short read gap. A later runtime coordinator must serialize compaction with reads before continuous/runtime compaction is enabled. H4 itself has no product scheduler or runtime compaction entry point.

## Canonical dataset layout

The canonical layout is Hive-style monthly partitioning:

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

Daily partitioning is deliberately not the default. It can be benchmarked later without changing FDD SQL semantics.

Partition values reject traversal, separators, NULs, or `=`. `timestamp_utc` remains a real Arrow timestamp; malformed input is rejected/skipped according to existing strict contracts rather than inventing a timestamp.

## Logical row schema

A logical history row retains:

```text
timestamp_utc
equipment_id (partition identity)
canonical FDD role columns...
```

`building_id`, `equipment_id`, `year`, and `month` are partition identity where applicable and should not be redundantly stored in every Parquet row unless a measured compatibility requirement proves it necessary.

Safe schema evolution rules are:

- adding a nullable role is allowed;
- missing optional roles remain null;
- categorical roles remain UTF-8;
- incompatible datatype changes fail clearly;
- no silent reinterpretation of a canonical role datatype.

## Append and small-file policy

Parquet is immutable-oriented. The normal write lifecycle is:

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
complete immutable Parquet part
       |
       v
crash-safe publish
```

Configuration:

```text
OPENFDD_PARQUET_FLUSH_ROWS=5000
OPENFDD_PARQUET_FLUSH_SECONDS=60
OPENFDD_PARQUET_TARGET_FILE_MB=128
OPENFDD_COMPACTION_MIN_FILES=8
OPENFDD_COMPACTION_ENABLED=true
```

Never append in place to one giant Parquet file and never emit one Parquet file per telemetry packet/sample.

Local publication writes a temporary sibling file, syncs the complete file, and atomically renames it into the final partition where normal filesystem rename semantics apply. Object storage in H5 must upload only complete objects; no code appends in place to an existing Parquet object.

## Query safety and memory

A historian approaching 1 TB does not imply 1 TB of RAM.

```text
OPENFDD_QUERY_MEMORY_MB=512
OPENFDD_DATAFUSION_SPILL_DIR=/workspace/.cache/datafusion-spill
```

Normal AFDD queries should include explicit building/equipment/time predicates so Hive pruning, Parquet statistics, timestamp predicate pushdown, and column pruning restrict reads to a small fraction of retained history. Generic interactive paths must be bounded or streamed rather than blindly materializing unlimited results into JSON.

## Legacy data classification

The repository still has pre-canonical paths that H6/H7 must migrate or demote safely:

| Usage | Classification | Direction |
| --- | --- | --- |
| `building=<id>/equipment=<id>/history.parquet` | legacy local Parquet sidecar | migrate explicitly to canonical monthly parts in H6 |
| one-row live Feather shards | legacy/interoperability | stop using as durability-critical in H7 |
| `telemetry_pivot.jsonl` | legacy live history | classify/migrate where identity is trustworthy; stop durability reliance in H7 |
| `telemetry_pivot.arrow` snapshot | bench/cache artifact | non-canonical |
| equipment `history.feather` | optional cache/interchange | retain only while consumers require it |

No legacy data is deleted before its consumers and preservation/migration requirements are audited.

## H5: S3-compatible storage and Railway

The generic application configuration target is:

```text
OPENFDD_STORAGE_URL=s3://openfdd-history
OPENFDD_S3_ENDPOINT=https://...
OPENFDD_S3_REGION=...
OPENFDD_S3_ACCESS_KEY_ID=...
OPENFDD_S3_SECRET_ACCESS_KEY=...
```

H5 must add direct generic `object_store` integration, DataFusion object-store registration, complete-object writes, virtual-hosted/path-style compatibility, credential redaction, central runtime cutover, and optional MinIO qualification. Provider-specific variable names belong in deployment configuration, not engine branches.

Railway mapping remains deployment-only:

```text
OPENFDD_STORAGE_URL=s3://${{bucket.BUCKET}}
OPENFDD_S3_ENDPOINT=${{bucket.ENDPOINT}}
OPENFDD_S3_REGION=${{bucket.REGION}}
OPENFDD_S3_ACCESS_KEY_ID=${{bucket.ACCESS_KEY_ID}}
OPENFDD_S3_SECRET_ACCESS_KEY=${{bucket.SECRET_ACCESS_KEY}}
```

The intended cloud topology is:

```text
openfdd-web (LAN/VPN only)
      |
private Railway ingress / private DNS
      |
openfdd-central (private)
      |
OPENFDD_STORAGE_URL=s3://<bucket>
      |
private S3-compatible bucket
```

The central container filesystem is cloud scratch, not the canonical historian. Secrets must never be returned by config/status APIs or written to logs.

## Local Docker / VM model

A normal local install needs no object-storage service:

```text
OPENFDD_STORAGE_URL=file:///data/openfdd
```

with a persistent Docker volume or host directory mounted at `/data/openfdd`. MinIO is optional test/advanced infrastructure for exercising the H5 S3 path, not a basic local dependency.

## Bulk analysis vs continuous AFDD

The historian supports two explicit operating modes:

```text
bulk        = import/history + operator-requested analysis; no scheduler
continuous  = live/incremental append + rolling scheduled AFDD
```

Importing historical data does **not** implicitly start a scheduler. H8 owns continuous scheduling, checkpoints, catch-up, run-now/backfill, and finding continuity.

Target configuration:

```text
OPENFDD_AFDD_MODE=bulk|continuous
OPENFDD_AFDD_INTERVAL_MINUTES=60
OPENFDD_AFDD_LOOKBACK_VALUE=24
OPENFDD_AFDD_LOOKBACK_UNIT=hours
```

A continuous run ends at the latest successfully persisted eligible telemetry timestamp, not blindly at wall clock. Rolling windows intentionally overlap so late-arriving BAS data can be evaluated on a subsequent cycle. Ingest durability and AFDD scheduling remain decoupled.

## Migration and operator tooling

H6 migration is explicit rather than a silent rewrite. It must discover legacy data, preserve timestamps/equipment identity/row counts, support dry-run and restart-safe behavior, avoid overwriting canonical parts, and emit a preservation report.

Operator historian stats should remain lightweight and include buildings, equipment, partitions, Parquet file count, bytes, small-file count, file-size distribution, oldest/newest timestamp, estimated rows, and storage backend without performing an expensive full scan on every UI load.

## Observability, backup, and restore

Historian/AFDD telemetry should reuse the existing tracing/observability stack. Useful counters/timers include ingest rows/bytes, flush count/duration, file count, compaction work, query duration/rows/bytes, AFDD cycle state, and data freshness. Never log S3 secrets.

Local deployments back up the configured storage root plus required small mutable application/session state. Object-storage deployments use the provider's durability/versioning/backup policy; production must not assume preview/staging and production share one object namespace.

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

1. **H1 Storage contract and audit** — merged.
2. **H2 Partitioned Parquet writer/micro-batches** — merged.
3. **H3 DataFusion dataset registration/query safeguards** — merged.
4. **H4 Offline local compaction** — merged.
5. **H5 S3-compatible backend + central/Railway/MinIO wiring** — next.
6. **H6 Migration + historian operator tooling** — not landed.
7. **H7 Live ingest durability cutover** — not landed.
8. **H8 Continuous AFDD scheduler/findings/API** — not landed.
9. **H9 React historian/AFDD operations UX** — not landed.
10. **H10 Scale and release qualification** — not landed.

Every phase must preserve existing FDD/weather behavior and pass the repository's changed-head CI/security/docs/review gates before merge.
