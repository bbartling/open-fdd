# Historian / Continuous AFDD architecture contract

> **SUPERSEDED HARD LOCKS (Wave-X 3.6.0+ / ADR-010):** Product historian is **TimescaleDB only**.
> **FORBIDDEN:** DataFusion product path, Arrow historian, Parquet co-canonical, Feather, dual-write,
> dual-read, “Parquet if Timescale miss”, sidecar mirror. Soft-OPEN ≠ FQ.
> Stay Rust for OSS central. Shared scientific truth = versioned `sql/schema` + `sql/fdd` pack hash
> (`sql/contract/manifest.json`). See [`../../docs/architecture/adr-010-timescale-hard-cutover.md`](../../docs/architecture/adr-010-timescale-hard-cutover.md).
>
> Historical Parquet/DataFusion sections below are **retired product law** — do not follow for new work.

## Hard locks (current — Timescale ONLY)

- **TimescaleDB / PostgreSQL is the canonical durable historian.**
- **Versioned SQL** in `sql/fdd/` + `sql/schema/` is FDD/analytics execution truth.
- **FORBIDDEN:** Parquet/Arrow/DataFusion/Feather as product historian or co-canonical store.
- **FORBIDDEN:** dual-write, dual-read, “Parquet if Timescale miss”, sidecar mirror.
- Feather/Arrow IPC (if any) is non-product interchange only — never the durable copy.
- Do not add Railway-specific historian engine forks.
- Historian, central, and dashboard ingress remain LAN/VPN/private-only (or authorized Soft-OPEN hub).
- Soft-OPEN ≠ FQ.

## Historical note (retired)

The remainder of this file documents the pre-3.6.0 Parquet/DataFusion contract for audit history only.
Do not implement dual-write bridges from it. Live ops: [`TIMESCALE_WAVE_X.md`](../../docs/operations/TIMESCALE_WAVE_X.md)
(`OPENFDD_DATABASE_URL`, `OPENFDD_HISTORIAN=timescale`, dual-write false). Soft-OPEN ≠ FQ.

## Generic storage contract (historical — pre-3.6.0 Parquet)

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
OPENFDD_S3_URL_STYLE=path|virtual
OPENFDD_S3_ALLOW_HTTP=false
```

Never log or return access/secret keys or session tokens. `OPENFDD_S3_ALLOW_HTTP=true` is for explicit local/test endpoints such as loopback MinIO only.

Legacy `OPENFDD_PARQUET_ROOT` may be recognized for migration/backwards compatibility, but do not silently pretend the legacy physical layout is the canonical layout.

## Canonical partitions

```text
history/
  building_id=<id>/
    equipment_id=<id>/

*(Historical body truncated in Soft-OPEN doc blast — full text in git history.)*
