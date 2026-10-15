---
title: Historian S3
nav_exclude: true
---

# S3-compatible historian operations

> **SUPERSEDED (Wave-X 3.6.0+ / [ADR-010](../architecture/adr-010-timescale-hard-cutover.md)):** Product historian is **TimescaleDB only** — no dual-write, no Parquet/S3 co-canonical path. Soft-OPEN ≠ FQ. Live bring-up: [`TIMESCALE_WAVE_X.md`](TIMESCALE_WAVE_X.md). The Parquet/S3/DataFusion guidance below is **historical** (pre-3.6.0 H5) and must not guide new deploys.

Open-FDD historically used the same Parquet historian contract on local disk and S3-compatible object storage. The engine stayed provider-neutral: AWS S3, MinIO, Railway Storage Buckets, and compatible providers mapped deployment settings into the same `OPENFDD_*` variables.

## Generic configuration

```text
OPENFDD_STORAGE_URL=s3://openfdd-history
OPENFDD_S3_ENDPOINT=https://storage.example.com
OPENFDD_S3_REGION=us-east-1
OPENFDD_S3_ACCESS_KEY_ID=<secret>
OPENFDD_S3_SECRET_ACCESS_KEY=<secret>
OPENFDD_S3_URL_STYLE=path
OPENFDD_S3_ALLOW_HTTP=false
```

`OPENFDD_S3_ENDPOINT` is optional for standard AWS S3. Explicit access/secret keys must be configured together; an optional session token requires that explicit pair. Endpoint URLs may not embed credentials. Credentials are never included in historian debug output.

`OPENFDD_S3_URL_STYLE=path` is the default. Use `virtual` only when the provider requires virtual-hosted requests. For a custom virtual-hosted endpoint, the runtime derives the bucket-qualified host required by the `object_store` S3 client. `OPENFDD_S3_ALLOW_HTTP=true` is for intentional local/test endpoints such as MinIO only.

The canonical query layout remains:

```text
s3://<bucket>/<optional-prefix>/history/
  building_id=<id>/equipment_id=<id>/year=YYYY/month=MM/part-*.parquet
```

DataFusion registers the object store once at `s3://<bucket>`, enables Parquet pruning, and exposes Hive partition columns as UTF-8. Building-scoped central analytics narrow the S3 listing root to `building_id=<id>/` before file discovery, so unrelated buildings are not scanned or listed for a scoped request.

## DataFusion runtime behavior

The historian query path uses the H3 resource contract in addition to object-store registration:

```text
OPENFDD_QUERY_MEMORY_MB=512
OPENFDD_DATAFUSION_SPILL_DIR=/var/tmp/openfdd-datafusion
```

Interactive materialization stayed row-bounded; streaming callers used Arrow record-batch streams. Month/building/equipment predicates remained available for DataFusion partition pruning. H5 did not replace immutable Parquet parts with per-sample objects. **Current tip (ADR-010):** TimescaleDB is the canonical historian — do not treat this S3/Parquet path as live product law.

Central keeps a small local building-scope index only to preserve the existing fail-closed `building=<id>` guard. This index contains empty directories, is refreshed from S3 delimiter listings, and is not durable historian data. Override its scratch location with `OPENFDD_S3_SCOPE_INDEX_DIR`. `OPENFDD_S3_SCOPE_REFRESH_SECONDS` controls the central refresh cadence (default 60 seconds).

## Local MinIO qualification

Start the optional S3-compatible test endpoint with:

```text
docker compose -f docker/compose.minio.yml up -d
```

Then configure Open-FDD:

```text
OPENFDD_STORAGE_URL=s3://openfdd-history
OPENFDD_S3_ENDPOINT=http://127.0.0.1:9000
OPENFDD_S3_REGION=us-east-1
OPENFDD_S3_ACCESS_KEY_ID=openfdd
OPENFDD_S3_SECRET_ACCESS_KEY=openfdd-local-test-only
OPENFDD_S3_URL_STYLE=path
OPENFDD_S3_ALLOW_HTTP=true
```

The example credentials are local-test-only. Do not use them outside an isolated development environment.

## Railway Storage Bucket

Railway is deployment configuration, not an engine branch. Map the bucket variables into Open-FDD:

```text
OPENFDD_STORAGE_URL=s3://${{bucket.BUCKET}}
OPENFDD_S3_ENDPOINT=${{bucket.ENDPOINT}}
OPENFDD_S3_REGION=${{bucket.REGION}}
OPENFDD_S3_ACCESS_KEY_ID=${{bucket.ACCESS_KEY_ID}}
OPENFDD_S3_SECRET_ACCESS_KEY=${{bucket.SECRET_ACCESS_KEY}}
OPENFDD_S3_URL_STYLE=virtual
OPENFDD_S3_ALLOW_HTTP=false
```

Use the URL style shown by the bucket credentials/configuration for that bucket; older or non-Railway S3-compatible deployments may require path style. The Rust engine does not read `RAILWAY_*` variables or branch on the provider name.

In the pre-3.6.0 S3 topology the Storage Bucket was the durable Parquet historian; container disk was scratch for DataFusion spill and the local building-scope index. **Current tip:** Timescale is canonical ([ADR-010](../architecture/adr-010-timescale-hard-cutover.md)). Open-FDD services remain LAN/VPN/private-ingress deployments; credentials and the central API must not be exposed through public unauthenticated ingress.
