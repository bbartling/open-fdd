---
title: Historian filesystem freeze (3.4.0)
parent: Operations
nav_order: 7
---

# Historian filesystem freeze — 3.4.0

Wave K **K2** contract pin for the single-tenant Parquet / DataFusion historian.
Living evidence: [`BUG_REPORT_OT_MODBUS_HAYSTACK.md`](BUG_REPORT_OT_MODBUS_HAYSTACK.md).
Patch trains: [`PATCH_CYCLE.md`](PATCH_CYCLE.md). Stress closeout: [`STRESS_CLOSEOUT.md`](STRESS_CLOSEOUT.md).

## Purpose

Freeze the **filesystem Parquet historian contract** before Wave L multi-client partitioning.

| Lock | Meaning |
|------|---------|
| Format | Durable historian = **Parquet** under `OPENFDD_STORAGE_URL` (or legacy `OPENFDD_PARQUET_ROOT`) |
| Query | **DataFusion** over Hive-partitioned `history/` (and `weather/`) |
| Scope of 3.4.0 | Last fully qualified **single-tenant** line — one Railway hub, one storage root |
| Non-goal | No Postgres (or other RDBMS) time-series; no Feather↔DB telemetry dual-write |

Wave L (3.5.x) may **partition** that same Parquet layout for many tenants. It must **not** rewrite or abandon this 3.4.0 pin semantics for single-tenant rollback.

## Canonical paths under `/workspace`

Railway central mounts durable data at **`/workspace`**. Hosted compose sets:

```text
OPENFDD_STORAGE_URL=file:///workspace/openfdd
```

(and, when needed for FDD package discovery parity, `OPENFDD_PARQUET_ROOT=/workspace/openfdd`).

### Root resolution (`parquet_root` / `local_file_root_from_env`)

Authoritative helpers:

| Helper | Location | Role |
|--------|----------|------|
| `fdd_store::local_file_root_from_env` | `crates/fdd_store/src/historian.rs` | Env → local `PathBuf` root |
| `fdd_store::history_partition_path` | same | Relative Hive path under that root |
| `analytics::historian::parquet_root` | `services/central/src/analytics/historian.rs` | Central/analytics root (calls `local_file_root_from_env` first) |
| `registry_api::parquet_root` | `edge/src/fdd/registry_api.rs` | Edge/FDD registry root (same env precedence) |

Precedence for the local file root:

1. `OPENFDD_STORAGE_URL` when `file://…` or a plain path  
2. Legacy `OPENFDD_PARQUET_ROOT`  
3. Dev fallbacks only (`OPENFDD_WORKSPACE` / `.cache/parquet`) — **not** the Railway pin layout

On Railway, the durable root is therefore:

```text
/workspace/openfdd
```

### Hive partition layout (frozen)

Relative to the storage root, equipment telemetry uses `history_partition_path`:

```text
history/building_id=<id>/equipment_id=<id>/year=<YYYY>/month=<MM>/
```

Weather uses `weather_partition_path`:

```text
weather/building_id=<id>/year=<YYYY>/month=<MM>/
```

Rules already enforced in `fdd_store`:

- Partition values are UTF-8 path literals (`year='2026'`, `month='09'` zero-padded).
- `safe_partition_value` rejects `/`, `\`, `..`, NUL, and `=`.
- Identity columns are Hive path columns; physical Parquet parts omit duplicate identity fields.

Legacy package sidecars under `building=<id>/` may still be **read** for scoped registration; **new** durable ingest targets the canonical `history/building_id=` tree only.

### Feather

Feather / Arrow-IPC dual-write and `OPENFDD_LEGACY_INGEST_MIRROR` are **retired** (Plan 4). Canonical durability is Parquet only. If any Feather artifacts remain on a volume from older images, treat them as non-canonical leftovers — do not revive dual-write in the 3.4.0 line.

## Backup / restore

Before every Railway image re-pin:

```bash
./scripts/railway_central_workspace_backup.sh
```

Default destination:

```text
~/openfdd-backups/railway/<UTC>/
```

(`OPENFDD_BACKUP_ROOT` overrides the parent; each run adds a `YYYYMMDDTHHMMSSZ` directory.)

Typical artifacts:

| File | Contents |
|------|----------|
| `central-workspace.tgz` | Tar of central `/workspace` (`openfdd` + `mqtt`, or whole tree) |
| `central-workspace.sha256` | Checksum |
| `central-workspace-inventory.txt` | Pre-backup `ls` / `du` sample |
| `mqtt-certs.tgz` | Optional MQTT certs (`OPENFDD_BACKUP_MQTT_CERTS`) |
| `README.txt` | Restore one-liner |

Restore (from the backup directory):

```bash
railway ssh -s <central-svc> -- sh -lc 'cd /workspace && tar -xzf -' < central-workspace.tgz
```

Never commit backup directories. Secrets in the tarball stay on local disk only.

## Railway volume rules

| Do | Do not |
|----|--------|
| Keep the **same** `/workspace` volume across upgrades | Delete / recreate the volume for an “upgrade” |
| Re-pin **images only** (GHCR `sha-<7>` tip on hub + fieldbus) | Treat a fresh empty volume as a normal upgrade path |
| Backup → re-pin → soak → smoke; log in BUG_REPORT | Rely on image layers for historian durability |

Durability model: **same volume (or same `s3://` bucket)**, not a per-message export. App updates replace container images; historian bytes remain on the mounted root.

See also [`RAILWAY_DEPLOYMENT_CHECKLIST.md`](RAILWAY_DEPLOYMENT_CHECKLIST.md) (“App updates must not wipe telemetry”).

## No silent format change in the 3.4.0 line

Within **3.4.0** (and remaining 3.3.x tips that feed the pin):

- Do **not** change Hive path shape, month/year padding, Snappy/part naming contract, or root env semantics without an explicit, documented migration and a new VERSION line.
- Do **not** switch the product historian to an RDBMS time-series store.
- Do **not** reintroduce Feather as durability.
- Compaction may rewrite **part files** inside an existing partition; it must not cross `building_id` / `equipment_id` / `year` / `month` boundaries or invent a new tree layout.

Readers and writers on a pinned 3.4.0 tip must agree on the paths above without ad-hoc rewrites.

## What Wave L may add later (without rewriting 3.4.0)

Wave L **multi-client shared hosting** (queued; coding only after BUG_REPORT shows **3.4.0 PINNED**) may add a **tenant prefix** (or per-tenant storage root) above the frozen relative tree, for example:

```text
# Conceptual — exact ADR lands as Wave K K3 / Wave L Phase-0
/workspace/openfdd/tenants/<tenant_id>/history/building_id=…/equipment_id=…/year=…/month=…
# or OPENFDD_STORAGE_URL scoped per tenant to a dedicated root
```

Constraints:

| Allowed in Wave L | Must preserve |
|-------------------|---------------|
| Tenant control-plane metadata (users/memberships) | Relative `history/building_id=/equipment_id=/year=/month=` semantics |
| Feature flag **OFF** by default; single-tenant = 3.4.0 behavior | Ability to roll back to 3.4.0 images on the same volume layout |
| Tenant-scoped DataFusion providers | Parquet + DataFusion as the historian (not Postgres TS) |

A tenant prefix is an **additive** isolation layer. It does not redefine what a 3.4.0 single-tenant root contains under `history/`.

## Cross-links

| Doc | Role |
|-----|------|
| [`BUG_REPORT_OT_MODBUS_HAYSTACK.md`](BUG_REPORT_OT_MODBUS_HAYSTACK.md) | Living pin / smoke / stress evidence |
| [`PATCH_CYCLE.md`](PATCH_CYCLE.md) | Tiny VERSION rev + Railway hub stress template |
| [`STRESS_CLOSEOUT.md`](STRESS_CLOSEOUT.md) | Full stress handbook (`run_railway_hub_stress.sh`) |
| [`RAILWAY_DEPLOYMENT_CHECKLIST.md`](RAILWAY_DEPLOYMENT_CHECKLIST.md) | Volume / image re-pin checklist |
| [`HISTORIAN_SCALE_QUALIFICATION.md`](HISTORIAN_SCALE_QUALIFICATION.md) | Scale / qualification notes |
| [`historian-s3.md`](historian-s3.md) | Object-store (`s3://`) variant of the same contract |
| [`patch_trains/openfdd_wave_k_340_filesystem_pin_program.plan.md`](patch_trains/openfdd_wave_k_340_filesystem_pin_program.plan.md) | Wave K master (repo mirror) |
| [`patch_trains/openfdd_wave_l_shared_db_mega_program.plan.md`](patch_trains/openfdd_wave_l_shared_db_mega_program.plan.md) | Wave L queued program |
| [`../../openfdd_agent_spec/HISTORIAN_PROGRAM.md`](../../openfdd_agent_spec/HISTORIAN_PROGRAM.md) | Historian phase ledger (H1–H7) |

## Acceptance for this freeze doc (K2)

- Operators and agents treat `/workspace/openfdd` + `history/building_id=…` as the pinned filesystem contract.
- Upgrades = backup + image re-pin; volume retained.
- Wave L design (K3 ADR) references this file and does not propose silent 3.4.0 path/format churn.
