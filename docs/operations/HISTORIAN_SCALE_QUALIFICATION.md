# Historian scale and release qualification

H10 provides a deterministic synthetic workload and a repeatable qualification path for the canonical Parquet/DataFusion historian. It is a test harness, not a second historian or a production data generator.

## Cheap changed-head gate

Run before expensive image or deployment tests:

```bash
python3 scripts/historian_scale_check.py
cargo test -p fdd_store -p fdd_sql -p fdd_rules -p fdd_bench
```

The H10 GitHub Actions workflow also boots the local CSV central + React containers and verifies `/api/health` plus a CSV preview smoke.

## Synthetic source

Generate deterministic JSONL source rows:

```bash
python3 scripts/historian_scale_generate.py \
  --buildings 1 \
  --equipment-per-building 10 \
  --days 30 \
  --interval-seconds 300 \
  --seed 20260822 \
  --output .cache/h10/source.jsonl
```

Generate incremental chunks for continuous-ingest/rolling-AFDD exercises without regenerating retained history:

```bash
python3 scripts/historian_scale_generate.py \
  --buildings 1 --equipment-per-building 10 \
  --duration-hours 1 --offset-hours 24 \
  --interval-seconds 300 --seed 20260822 \
  --output .cache/h10/source.jsonl --append
```

The source is intentionally portable. Qualification adapters must feed it through the production historian ingest/writer contract rather than writing ad-hoc Parquet files behind that contract.

## Representative query shapes

`scripts/historian_scale_workloads.sql` defines the stable H10 workload set:

- equipment/day
- equipment/month
- building/hour
- monthly aggregation
- bounded weather join
- representative FDD proof query

Production AFDD registry execution remains mandatory; the representative FDD query is only a stable benchmark shape.

## Scale targets

Use the same source/harness at increasing sizes. Do not make the normal PR gate generate multi-GB artifacts.

| Target | Purpose | Expected execution |
| --- | --- | --- |
| small | changed-head correctness, pruning/query shape, local container smoke | GitHub Actions / developer machine |
| ~1 GB | first meaningful storage/query benchmark | manual local or CI runner with adequate disk |
| ~10 GB | sustained partition/query/rolling-AFDD check | manual benchmark host |
| ~100 GB | object-count, pruning, compaction and memory behavior | dedicated benchmark host / object store |
| ~1 TB architecture check | validate retained-history design assumptions | dedicated environment; never ordinary PR CI |

For each run capture at minimum: generated/ingested rows, canonical files, partitions, bytes, query wall time, peak process/container memory where available, AFDD cycle time, and evidence of building/equipment/month/time pruning where measurable.

## Local container qualification

The changed-head H10 workflow runs:

```bash
./scripts/release/smoke_csv_central_boot.sh
```

For a candidate GHCR build, prefer an immutable `sha-<shortsha>` tag for reproduction. A floating tag is useful for convenience but should not be the evidence recorded in a qualification result.

## MinIO / S3-compatible qualification

Use the existing S3-compatible historian configuration and local MinIO recipe documented in `docs/operations/historian-s3.md`. H10 does not add a provider-specific storage path. The same canonical layout, DataFusion registration, AFDD execution, and stats expectations apply.

## Railway qualification

Railway qualification is deployment verification, not engine branching. Use `docs/operations/RAILWAY_DEPLOYMENT.md` and pin the exact candidate image SHA while testing. Confirm at minimum:

- central `/api/health`
- React web reaches central through private Railway DNS
- persistent canonical storage is configured as documented
- AFDD Config shows scheduler/watermark/cycle state without fabricated values
- Run AFDD now uses the H8 execution engine
- MQTT Config remains bounded/read-only and does not expose broker credentials
- sustained telemetry does not create an unbounded monitor buffer

Do not describe a Railway trial as production-hardened public SaaS. Central, historian, MQTT, and fieldbus ingress remain private/LAN/VPN-oriented per the repository security contract.
