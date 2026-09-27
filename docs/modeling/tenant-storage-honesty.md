---
title: Tenant storage path honesty (DM-05)
parent: Modeling
nav_order: 9
permalink: /modeling/tenant-storage-honesty/
---

# Tenant storage path honesty (DM-05)

Honest layout contract for package / Parquet / legacy graph storage under
multi-tenant (MT) mode. Update when paths migrate.

## What is shipped today

| Surface | Path shape | Tenant isolation |
| --- | --- | --- |
| Package CSV tree | `workspace/data/csv_buildings/<building_id>/` | **Building ACL on HTTP** (`deny_if_building_out_of_scope`); filesystem is hub-root, not `tenants/{tid}/` |
| Equipment type stamps | `…/csv_buildings/<bid>/equipment_types.json` and Parquet `building=<bid>/equipment_types.json` | Same building id; stamps preferred (DM-04) |
| Historian Parquet | `OPENFDD_STORAGE_URL` → hub-root `building=<bid>/…` **or** optional `tenants/{tid}/building=<bid>/…` (Wave U V7 dual-read) | JWT membership gates reads/writes; read the newer Parquet tree (tie → hub-root) |
| Session / fault config | building-keyed session files | ACL on `/api/fdd/session-config` |
| Legacy Oxigraph / Haystack grid | process-global `data/model/*` (edge path) | **Not multi-tenant ACL** — do not expose as a shared-tenant service |

## Dual-read + migrate (Wave U V7)

- **Reads:** `fdd_store::resolve_building_read_root` loads the newer Parquet tree of `tenants/{tid}/…` and hub-root `building=*`. A tree counts only when it contains `.parquet` (an empty legacy `building=` directory does not). Freshness is the max of file mtime and `part-` / `compact-` UTC stamps in the file name; a tie prefers hub-root so a copied or compacted tenant snapshot cannot mask live hub parts. A tenant-only tree still reads `tenants/{tid}/…`. Ambiguous identical labels under two tenants without a preferred tid fall through to hub-root (fail closed).
- **Migrate:** additive copy via `scripts/ops/wave_u_v7_tenant_path_migrate.sh` of each hub-root building tree into `tenants/{tid}/`. The helper's site map is deployment config, not a product default. Never deletes hub-root.
- **ACL:** foreign tenant deny; hub_admin sees all (`TenantContext::allow_building` + gate 31 / preauth matrix).

## Soft-OPEN closed by V7

- Optional on-disk prefix `tenants/{tid}/building=…` — **CLOSED** as product dual-read + migrate helper (`wave-o1-tenant-path-migrate`). Live hub APPLY remains operator-authorized after Railway backup.

## What remains Soft-OPEN

- Legacy global RDF store is **unavailable** as a product multi-tenant graph —
  report unavailable / Soft-OPEN, never PASS via empty SPARQL lists.
- CSV package trees under `workspace/data/csv_buildings/` stay hub-root (HTTP ACL only).

## Operator proof (MT ON)

```bash
# Operator A: own building → 200; foreign building → 403/404
# Covered by security harness Y checks + gate 22 / 25 / 25b.
# Dual-read unit: cargo test -p fdd_store dual_read
# Migrate dry-run: HUB_PARQUET_ROOT=… ./scripts/ops/wave_u_v7_tenant_path_migrate.sh
```

Model/ECM qualification gate (wired for stress profiles; FQ on S4 tip):
[`scripts/nightly-ot-bench/36_model_ecm_qualification.sh`](../../scripts/nightly-ot-bench/36_model_ecm_qualification.sh).
