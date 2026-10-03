---
title: Data model JSON / RDF crosswalk
parent: Modeling
nav_order: 14
permalink: /modeling/data-model-json-rdf-crosswalk.html
---

# `openfdd_data_model_v1` ↔ native RDF ↔ strict Haystack

Crosswalk for package **Mapping inventory** exports. Telemetry and FDD math stay
in Parquet/DataFusion — not in this table.

Profile for strict Haystack: [`ofdd_haystack_projection_v1`](haystack-rdf-profile.html).

## Native JSON (`openfdd_data_model_v1`)

Produced by SPA `buildMappingManifest()` and equivalent server inventory JSON.

| JSON field | Semantics | Native TTL (`openfdd_data_model_v2`) | Strict `ofdd_haystack_projection_v1` |
| --- | --- | --- | --- |
| `schema` | Always `openfdd_data_model_v1` | N/A (Turtle has no single root object) | N/A |
| `generated_at` | Client export timestamp | Not emitted | Not emitted |
| `building_id` | Site id | `ofdd:buildingId` literal on `ofdd:Building` | `ph` site ref (C3) |
| `unit_system` | `imperial` / `metric` | Not emitted | Not in strict equip graph |
| `validation.*` | Aggregate counts | Not emitted | Not emitted |
| `warnings[]` | Site-level strings | Not emitted | Projection report only |
| `equipment[].equipment_id` | Stable id | `ofdd:equipmentId` literal | Stable export IRI local name |
| `equipment[].equipment_type` | Stamp classifier | `ofdd:equipmentType` literal | `ph` equip tags when stamped |
| `equipment[].equipment_type_source` | Provenance | Not emitted | Native metadata only |
| `equipment[].parent_ahu` | Confirmed parent id | `ofdd:parentAhu` ref if source ≠ `inferred` | Containment/supply edge (C3) |
| `equipment[].parent_ahu_source` | `package` / `inferred` | Controls parent edge emission | Never promote `inferred` |
| `equipment[].roles` | column → SQL role | `ofdd:roleBinding` blank nodes | **Not** auto-mapped to Haystack tags |
| `equipment[].columns[]` | Per-column status | Partially reflected in roles/unmapped | Point candidates (C3) |
| `equipment[].unmapped_columns` | No SQL role | `ofdd:unmappedColumn` literals | Omitted unless mapped in C3 |
| `equipment[].ambiguous_roles` | role → [columns] | **Not emitted** | Selection required before strict point |
| `equipment[].blockers` | Human-readable | **Not emitted** | Projection report |
| `equipment[].warnings` | Per-equipment | **Not emitted** | Projection report |
| `equipment[].sampling` | Historian span sample | Not emitted | Not emitted |
| `equipment[].ok` | Rollup flag | Not emitted | Not emitted |

### Lossy native TTL (by design today)

Package TTL is an inventory **sketch**, not a lossless JSON round-trip. Quality
diagnostics in JSON are intentionally omitted from Turtle until C3 projection
reports unify both views.

## Strict Haystack omissions (intentional)

C3 `ofdd_haystack_projection_v1` (from native `openfdd_semantic_meta_v1` only):

- No `ph:equip` / `ph:point` instances from SQL roles alone.
- No marker tags inferred from role names (`sat` ≠ `ph:sensor`).
- Unknown vendor tags without defs → excluded + projection report.
- Ambiguous roles / intentional exclusions → omitted + reported.
- False/null/empty marker strings never become `ph:hasTag`.
- Unknown units stay in native metadata; strict graph omits typed unit literals.

## Import / export directions

| Direction | Supported (product) | Test plan owner |
| --- | --- | --- |
| ZIP compact map → SQL roles | **Yes** (existing ingest) | HR-01 package tests |
| Inventory → native JSON download | **Yes** | Vitest `mappingApi` |
| Inventory → native TTL (SPA + `GET …/mapping/ttl`) | **Yes** | Vitest + Rust `data_model_ttl` |
| Native semantic meta → JSON | **Yes** (`GET …/mapping/semantic-meta`) | C3 HR-04 |
| Native semantic meta → strict Haystack TTL | **Yes** (`GET …/mapping/haystack.ttl` + `…/haystack-projection`) | C3 HR-03/04 Rust + RDFLib |
| Strict Haystack TTL → native revision | **No** (not lossless; not advertised) | — |
| Haystack JSON grid → product ingest | **No** (not advertised) | — |
| ZIP → strict Haystack without native sidecar | **No** | Requires C2 `semantic_meta.json` |

Do not describe native TTL as “Haystack RDF export” in UI or docs. Strict Haystack uses profile `ofdd_haystack_projection_v1` with defs pin `ph-markers-allowlist-v1`.

## Code pointers

| Component | Path |
| --- | --- |
| JSON manifest | `frontend/web/src/api/mappingApi.ts` |
| Browser TTL | `frontend/web/src/api/dataModelTurtle.ts` |
| Central native TTL | `edge/src/csv_ingest/data_model_ttl.rs` |
| Strict Haystack projection | `edge/src/csv_ingest/haystack_projection.rs` |
| Native semantic meta | `edge/src/csv_ingest/semantic_meta.rs` |
| Inventory SoT | `edge/src/csv_ingest/package.rs` |

Synthetic crosswalk fixtures: `scripts/fixtures/haystack_rdf/`.
