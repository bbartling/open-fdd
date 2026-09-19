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
