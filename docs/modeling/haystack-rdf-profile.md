---
title: Haystack RDF compatibility profile
parent: Modeling
nav_order: 13
permalink: /modeling/haystack-rdf-profile.html
---

# Open-FDD Haystack projection profile — `ofdd_haystack_projection_v1`

**Status:** C3 product tip (#1001) implements strict export from native
`openfdd_semantic_meta_v1` via `GET …/mapping/haystack.ttl` (defs pin
`ph-markers-allowlist-v1`). Passing this document alone does **not**
establish full Haystack server interoperability, FDD readiness, or a live SPARQL service.

This profile names the **strict Haystack RDF interchange** Open-FDD will target
in wave C3+. It is separate from today's **native** package inventory exports
(`openfdd_data_model_v1` JSON and `openfdd_data_model_v2` Turtle under
`urn:openfdd:ns#`).

Requirements source: [`openfdd_agent_spec/HAYSTACK_RDF_ROLLOUT.md`](../../openfdd_agent_spec/HAYSTACK_RDF_ROLLOUT.md)
(HR-01–HR-12).

## Compatibility layers (do not conflate)

| Layer | Meaning | C1 status |
| --- | --- | --- |
| RDF syntax | Parseable Turtle/JSON-LD | Native TTL is valid RDF; not yet strict Haystack |
| Haystack semantics | Terms resolve to pinned `ph` defs; markers/refs valid | **Not claimed** for package TTL |
| Site mapping completeness | Roles, topology, units sufficient for FDD | Package inventory + diagnostics |
| FDD readiness | DataFusion roles populated | Existing SQL path |
| Graph/API services | Central SPARQL, authenticated exports | SPARQL **unavailable** on central (C4) |

## Pinned vocabulary

| Prefix | Base IRI | Pin policy |
| --- | --- | --- |
| `ph` | `https://project-haystack.org/def/ph#` | Haystack Project defs as published for Haystack 4.x RDF mapping ([Rdf](https://project-haystack.org/doc/docHaystack/Rdf), [Json](https://project-haystack.org/doc/docHaystack/Json)) |
| `ofdd` | `urn:openfdd:ns#` | Open-FDD native inventory + engineering extensions only |

Implementation must record the **exact defs bundle revision** used in CI when
C3 lands (git tag, npm package, or pinned download hash). C1 locks the name
`ofdd_haystack_projection_v1` and the namespace rules below — not a product tip.

## Instance mapping (strict projection)

Follow Haystack RDF instance rules:

1. **Sites, equips, points** are distinct resources with Haystack classes from
   `ph` where the source metadata supports the tag set.
2. **Marker tags** attach via `ph:hasTag` to marker resources — never invent a
   marker because a SQL role exists.
3. **Typed values** use documented XSD / Haystack value forms; **references**
   point to instance blank nodes or stable IRIs per export policy.
4. **Blank nodes** are ephemeral labels in a given serialization. Persistent
   identity is Open-FDD's internal site/equipment/point id + tenant scope, mapped
   at export time (HR-02).
5. **Never mint** Open-FDD extension terms inside `ph` or Brick IRIs. Use
   `urn:openfdd:ns#` with documented semantics and optional shapes.

## Unknown tags and intentional exclusions

- Tags without a pinned def are **excluded from the strict projection** and listed
  in a **projection report** (omitted term, source column/id, reason).
- Source facts remain in **native metadata** (JSON sidecars / persisted revision).
- Operator **intentional exclusions** (not FDD inputs) are not promoted to Haystack
  points; they appear in native inventory only.

## Units: value vs point metadata

Haystack RDF leaves some unit-on-value semantics as evolving spec work. This
profile distinguishes:

| Concept | Strict Haystack projection | Native Open-FDD metadata |
| --- | --- | --- |
| Point `unit` def | Emit when known and def-backed | Store on point record |
| Numeric reading | Value + compatible unit when spec allows | Parquet historian (canonical telemetry) |
| Unknown unit | Omit typed strict literal; report `unknown_unit` | Retain `unit_status: unknown` and vendor text |

Do not infer `unit` from column name suffixes or split SQL role strings.

## Uncertainty and FDD selection (HR-05)

These states stay explicit in native exports:

- **Ambiguous roles** — multiple columns mapped to one SQL role without selection
  evidence.
- **Missing topology** — e.g. stamped VAV without confirmed `parent_ahu`.
- **Duplicate legitimate sensors** — multiple valid Haystack points; FDD policy
  chooses inputs separately.

Strict projection must **not** pick the first column or promote inferred parents
to fact edges. Package TTL today already skips `parent_ahu_source=inferred`
(DM-04); strict Haystack inherits that rule.

## Authority and revisions (HR-07 preview)

One **authoritative native revision** per tenant/site. JSON, Turtle, and graph
views are **derived** from that revision. C2 adds persistence; C3 adds strict
projection. See [ADR — data model graph](../architecture/ADR_data_model_graph.html).

## Strict vs native export

| Export | Schema / profile | Purpose |
| --- | --- | --- |
| Native JSON | `openfdd_data_model_v1` | Full inventory + diagnostics for agents/UI |
| Native TTL | `openfdd_data_model_v2` (Turtle) | Compact RDF view of roles/unmapped columns |
| Strict Haystack TTL/JSON | `ofdd_haystack_projection_v1` | Interchange with pinned `ph` semantics (C3+) |

Field-level mapping: [data-model JSON/RDF crosswalk](data-model-json-rdf-crosswalk.html).

## Synthetic conformance fixtures

Independent answers (not exporter output):

`scripts/fixtures/haystack_rdf/` — see README there.

## Related

- [RDF vocabulary notes (DM-10 narrow)](rdf-vocabulary.html) — legacy edge grid
- [Data model TTL export](data-model-ttl.html) — native package TTL
- [Consumer route matrix](consumer-route-matrix.html)
