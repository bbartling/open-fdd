---
title: ADR — Data model graph contract
parent: Architecture
nav_order: 12
---

# ADR — Shared HVAC vocabulary vs tenant instance models

- **Status:** Accepted (2026-09-19) — Wave S2
- **Context tip:** product hub **3.5.31** / Wave S1 OPS PINNED; graph fixes continue on S5
- **Handoff:** [`.cursor/plans/wave_s_data_model_graph_review_handoff.md`](../../.cursor/plans/wave_s_data_model_graph_review_handoff.md)
- **Route matrix:** [`../modeling/consumer-route-matrix.md`](../modeling/consumer-route-matrix.md)
- **Haystack strict profile (C1):** [`../modeling/haystack-rdf-profile.md`](../modeling/haystack-rdf-profile.md)
- **JSON/RDF crosswalk:** [`../modeling/data-model-json-rdf-crosswalk.md`](../modeling/data-model-json-rdf-crosswalk.md)

## Context

Operators need vendor-neutral HVAC models, tenant-scoped visibility, JSON + Turtle
exports, and (eventually) SPARQL over relationships. Engineering capacities must
feed existing PyPI ECM tools without putting Python on the product request path.
Two namespaces already exist in-tree (`urn:openfdd:ns#` for package TTL;
`https://open-fdd.dev/model#` for legacy commissioning RDF).

## Decision

1. **One versioned shared vocabulary** (classes, properties, units, provenance
   rules) across vendors. Publish as ontology/shapes under `docs/modeling/` +
   `.ttl` (S5). Tenant equipment/evidence instances are **separate** datasets —
   never ship every customer’s private graph in one shared file loaded wholesale
   per request.
2. **Vendor ≠ tenant.** Manufacturer / protocol names never confer access.
   Access = authenticated membership + active tenant + allowed site/object scope.
   A vendor service account may hold explicit grants to multiple customers.
3. **One authoritative revision per tenant/site.** Compact package maps /
   `columns.csv` and DataFusion FDD contracts remain. Graph/TTL views are
   **derived projections**. Do not make JSON, TTL, and a store independently
   writable authorities. An RDF-authoritative migration needs its own
   migration/rollback ADR.
4. **Telemetry / FDD math stay in Parquet + DataFusion.** Use indexed RDF/SPARQL
   for semantic relationships. Keep typed lookups for simple keys; do not replace
   every dictionary lookup with SPARQL for appearance.
5. **Physical isolation:** prefer tenant-scoped stores/datasets (or demonstrably
   restricted query datasets). Named graphs may organize sites/revisions; a named
   graph is **not** an ACL.
6. **Export:** authorized site → Turtle (`urn:openfdd:ns#` package projection) +
   application JSON. Dataset exports that preserve named-graph boundaries need
   TriG/N-Quads with separate authorization. Application JSON is not automatically
   JSON-LD.
7. **Namespace freeze (until S5 migration note):**
   - Product package mapping TTL / SPA export: **`urn:openfdd:ns#`**
   - Legacy commissioning / edge RDF helpers: **`https://open-fdd.dev/model#`**
   - Do not mint Open-FDD engineering properties inside Haystack or Brick namespaces.
8. **Camber** ([yroussev/camber](https://github.com/yroussev/camber), Apache-2.0)
   is an **external algorithm reference** for PyPI oracle / M&V ports only.
   Forbidden: Camber in GHCR request path; Camber OT adapters; `camber serve` as
   product UI.
9. **M&V product UI:** charts live on **Metering** (or a dedicated radio) — not
   Overview Plotly (Wave S4).
10. **Haystack RDF track (2026 — wave C1+):** Name the strict interchange profile
    **`ofdd_haystack_projection_v1`** ([profile doc](../modeling/haystack-rdf-profile.md)).
    **Native** exports remain `openfdd_data_model_v1` JSON and `openfdd_data_model_v2`
    Turtle (`urn:openfdd:ns#`). Strict Haystack TTL/JSON is a **derived projection**
    from the authoritative native revision — not a second writable SoT. Unknown tags
    without pinned defs are omitted from strict output with an explicit projection
    report; native metadata retains source facts. Open-FDD extensions stay in
    `urn:openfdd:ns#`; never mint inside Haystack/Brick IRIs.
11. **Identity (DM-01/02):** Export IRIs use reversible `enc_<utf8-hex>` segments
    for unsafe labels; building/equipment tuple subjects use `ofdd:eq_<b>__<e>`.
    Tenant scope is server-derived — a named graph or client-supplied tenant id is
    not authorization (unchanged).
12. **Central package RDF + SPARQL:** Product central materializes a **scoped
    package RDF dataset** from committed native `semantic_meta` + pinned Haystack
    defs (`GET …/haystack-dataset`, schema `ofdd_haystack_central_dataset_v1`).
    That dataset is **not** the legacy `edge/src/model` commissioning graph.
    Package-graph SPARQL is server **template** execution (`POST /api/model/sparql`
    with `query_id`) returning `ofdd_haystack_typed_bindings_v1` (C4 H9). Free-form
    client SPARQL is rejected. Graph-driven FDD/ECM consumers (H10+) are still
    required before closing #1002. MCP must not PASS via empty lists.

## Consequences

- S5 implements injective IRI encoding, tenant-scoped model storage, SPARQL
  honesty, engineering quantity vocab, and stress gates.
- MCP/central must report **unavailable** where `/api/model/sparql` is not on
  product central (see route matrix) — never empty-list PASS.
- Optional Brick mappings require an explicit crosswalk doc; a prefix alone is
  not interoperability.

## Non-goals

- Wholesale ontology rewrite or RDF-authoritative ingest in Wave S.
- BTL / Clause 9 claims.
- Camber as a runtime dependency of central/web.
