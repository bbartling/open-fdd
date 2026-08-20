# Historian / Continuous AFDD architecture contract

This file is the software-engineering agent summary for the canonical Open-FDD historian. Full rationale and audit: [`../../docs/architecture/historian.md`](../../docs/architecture/historian.md).

## Hard locks

- **Parquet is canonical durable history.**
- **Arrow is in-memory execution.**
- **DataFusion is SQL/FDD execution.**
- Feather/Arrow IPC is cache/export/interchange only; never depend on it as the only durable copy.
- No PostgreSQL, TimescaleDB, InfluxDB, ClickHouse, DuckDB, or SQLite as the canonical historian.
- Do not add Railway-specific historian engine code.
- Normal local installs must work without MinIO.

## Generic storage contract

Local/VM:

```text
OPENFDD_STORAGE_URL=file:///data/openfdd
```

S3-compatible:

```text
OPENFDD_STORAGE_URL=s3://openfdd-history
OPENFDD_S3_ENDPOINT=https://...
OPENFDD_S3_REGION=...
OPENFDD_S3_ACCESS_KEY_ID=...
OPENFDD_S3_SECRET_ACCESS_KEY=...
```

Never log or return access/secret keys.

Legacy `OPENFDD_PARQUET_ROOT` may be recognized for migration/backwards compatibility, but do not silently pretend the legacy physical layout is the canonical layout.

## Canonical partitions

```text
history/
  building_id=<id>/
    equipment_id=<id>/
      year=YYYY/
        month=MM/
          part-<timestamp>-<unique>.parquet

weather/
  building_id=<id>/
    year=YYYY/
      month=MM/
        part-<timestamp>-<unique>.parquet
```

Initial partition strategy is building + equipment + year + month. Do not introduce daily partitioning without benchmark evidence.

Partition values must reject traversal/separators/NUL/`=`. `timestamp_utc` remains a real Arrow timestamp; never invent timestamps for bad input.

## Append and small-file contract

Never append in place to one giant Parquet file and never emit one Parquet file per telemetry packet/sample.

```text
OPENFDD_PARQUET_FLUSH_ROWS=5000
OPENFDD_PARQUET_FLUSH_SECONDS=60
OPENFDD_PARQUET_TARGET_FILE_MB=128
```

Flush on rows OR time OR clean shutdown. Local publication is temporary-file + fsync/close + atomic rename where supported. Object storage uploads only complete objects.

Initial Parquet compression direction is Snappy for low edge/VM CPU while retaining statistics/predicate pruning. Change only with measured evidence.

## Compaction contract

```text
OPENFDD_COMPACTION_ENABLED=true
OPENFDD_COMPACTION_MIN_FILES=8
OPENFDD_PARQUET_TARGET_FILE_MB=128
```

Compact partition-by-partition with bounded memory. Publish/validate replacement before deleting input parts. AFDD queries and ingestion must remain safe during compaction.

## DataFusion/query contract

The long-term `history` table is the logical dataset root, with Hive columns exposed to SQL:

```text
building_id, equipment_id, year, month
```

Do not make recursive local filesystem globbing the permanent historian abstraction. FDD SQL should not know physical filenames.

A large historian must not be collected into RAM. Generic/interactive result paths need row limits/streaming/pagination. Target config:

```text
OPENFDD_QUERY_MEMORY_MB=512
OPENFDD_DATAFUSION_SPILL_DIR=...
OPENFDD_QUERY_MAX_ROWS=10000
```

Rule execution can retain bounded result behavior as long as FDD parity remains intact.

## Operating modes

Explicitly distinguish:

```text
bulk        = import/history + operator-requested analysis; no scheduler
continuous  = live/incremental append + rolling scheduled AFDD
```

Target config:

```text
OPENFDD_AFDD_MODE=bulk|continuous
OPENFDD_AFDD_INTERVAL_MINUTES=60
OPENFDD_AFDD_LOOKBACK_VALUE=24
OPENFDD_AFDD_LOOKBACK_UNIT=hours|days|minutes
```

Interval and lookback are independent.

Continuous AFDD uses a defined window ending at the latest successfully persisted eligible telemetry timestamp. Rolling windows intentionally overlap for late-arriving data. Do not optimize to only `timestamp > last_run` unless a specific rule proves that safe.

Ingest durability and FDD scheduling are decoupled: a Parquet flush does not synchronously run all FDD.

## Scheduler locks

- state/checkpoint survives restart;
- one due catch-up run after downtime, not one job per missed tick;
- prevent overlapping cycles for the same scope;
- ingestion continues while AFDD runs;
- scheduled and manual run-now use the same execution engine;
- historical replay/backfill is explicit and chunked;
- building/rule failures should be isolated where existing contracts allow it.

## Continuous finding continuity

Overlapping AFDD windows must continue one fault episode instead of inserting a visually new finding every hour. Preserve existing contracts first, then use stable episode identity with first/last seen, status, occurrence/evaluation metadata as needed.

## Railway mapping

Railway is deployment configuration only:

```text
openfdd-web (public)
  -> openfdd-central.railway.internal:8080 (private)
  -> Railway Storage Bucket (private S3-compatible)
```

Map Railway bucket variables (`BUCKET`, `ENDPOINT`, `REGION`, `ACCESS_KEY_ID`, `SECRET_ACCESS_KEY`) into Open-FDD's generic `OPENFDD_*` variables. Do not read `RAILWAY_*` in historian engine code.

The central container filesystem is ephemeral cloud scratch, not the canonical historian. A volume may still hold small mutable application/session state where needed.

## Local VM mapping

IT-hosted VM/dashboard deployments use the same images and `file://` storage, with persistent Docker volume/host disk and central bound privately. MinIO is optional only for testing the S3 path.

## Validation

Every implementation PR touching this architecture must preserve FDD/weather behavior and run the relevant repo gates. Never weaken tests to get green.

Scale target: hundreds of GB to ~1 TB retained history while normal continuous AFDD scans only the configured building/equipment/time window through partition/statistics/column pruning.
