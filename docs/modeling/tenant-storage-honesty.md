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
| Historian Parquet | `OPENFDD_STORAGE_URL` → `building=<bid>/…` or canonical `history/building_id=<bid>/…` | Building-scoped parts; JWT membership gates reads/writes |
| Session / fault config | building-keyed session files | ACL on `/api/fdd/session-config` |
| Legacy Oxigraph / Haystack grid | process-global `data/model/*` (edge path) | **Not multi-tenant ACL** — do not expose as a shared-tenant service |

## What is Soft-OPEN

- Optional on-disk prefix `tenants/{tid}/building=…` (see Soft-OPEN
  `wave-o1-tenant-path-migrate`). Hub-root `building=*` remains the product path.
- Identical building labels across two tenants are isolated by **JWT membership**,
  not by filesystem namespace. Do not claim filesystem path uniqueness until the
  optional migrate lands.
- Legacy global RDF store is **unavailable** as a product multi-tenant graph —
  report unavailable / Soft-OPEN, never PASS via empty SPARQL lists.

## Operator proof (MT ON)

```bash
# Operator A: own building → 200; foreign building → 403/404
# Covered by security harness Y checks + gate 22 / 25 / 25b.
```

Model/ECM qualification gate (wired for stress profiles; FQ on S4 tip):
[`scripts/nightly-ot-bench/36_model_ecm_qualification.sh`](../../scripts/nightly-ot-bench/36_model_ecm_qualification.sh).
