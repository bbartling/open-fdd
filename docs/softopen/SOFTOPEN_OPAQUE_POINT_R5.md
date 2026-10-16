# Soft-OPEN R5 — opaque point IRI → Timescale SQL

Soft-OPEN ≠ FQ.

## Contract

| Piece | Soft-OPEN behavior |
| --- | --- |
| Mint | `urn:openfdd:site/{bid}/equip/{eid}/point/{key}` via `iri_segment` / `enc_` hex |
| Parse | `parse_opaque_point_iri` → `{building_id, equipment_id, point_key}` |
| SQL key | Exact `openfdd_key = "{equipment_id}.{point_key}"` — **no** identity invent via `split_part` |
| API | `GET /api/model/point-resolve?point_iri=…` (+ optional `include_history=true&max_points=`) |
| History plan | `ofdd_haystack_history_binding_plan_v2` — approved series rows enrich `point_iri` + `openfdd_key` (+ `model_revision`); inventory `openfdd_key` conflict / IRI mismatch → reject |

## Soft-OPEN honesty

- Resolve works without ACME `semantic_meta` (opaque IRI is the handle).
- History is Timescale `sample` Soft-OPEN only; empty rows are honest, not FQ site proof.
- History consumer enrichment is Soft-OPEN hygiene — not C2–C6 Haystack FQ / live site SPARQL proof.
- JWT + building scope required; Soft-OPEN ≠ FQ RDF/SPARQL site qualification.

Locks: no Soft-OPEN backups · volume Deletes owner-UI BLOCKED · Soft-OPEN ≠ FQ.
