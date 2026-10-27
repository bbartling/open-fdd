# Soft-OPEN R5 — ACME semantic_meta tip reachability

> **Historical (Railway retired 2026-10-26).** Railway and cloud web-app hosting are retired; Railway references below are `historical/non-executable`. Hosting is the local single-host stack: [LOCAL_HOSTING.md](../operations/LOCAL_HOSTING.md).

Soft-OPEN ≠ FQ. **No volume heroics** (no package import / volume mutate from Soft-OPEN agents).

## Tip-proven (Railway Soft-OPEN hub)

| Check | Result |
| --- | --- |
| `GET /api/csv/import/package/mapping/semantic-meta?building_id=ACME` | **200** `ok=true`, `present=false`, schema `openfdd_semantic_meta_v1` |
| `GET /api/fdd/equipment?building_id=ACME` | **200** `count=0`, engine `timescale-sql` |
| JWT free-form / template SPARQL on ACME | Fail-closed missing `semantic_meta` (after #1244: Update/SERVICE reject **before** meta) |
| SPARQL predefined catalog | **200** (includes `mech_system_summary`) — catalog Soft-OPEN without site meta |

## Soft-OPEN interpretation

- ACME is tip-reachable as an **empty Soft-OPEN site identity** without RDF sidecar.
- `present=false` is honest Soft-OPEN — not a greenwash “SPARQL site PASS”.
- Seeding ACME semantic_meta / package map requires an authorized import path (not Soft-OPEN overnight volume work).

## Product Soft-OPEN contract (3.6.13+)

Semantic-meta GET includes `soft_open_neq_fq: true` and a short note when `present=false`.

Locks: Soft-OPEN ≠ FQ · no Soft-OPEN backups · volume BLOCKED_UI_OWNER.
