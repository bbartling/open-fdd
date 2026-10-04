---
title: Haystack RDF compatibility profile
parent: Modeling
nav_order: 13
permalink: /modeling/haystack-rdf-profile.html
---

# Open-FDD Haystack projection profile — `ofdd_haystack_projection_v1`

**Status:** C3 audit repair (#1123 / #1001) implements strict export from native
`openfdd_semantic_meta_v1` via `GET …/mapping/haystack.ttl` (defs pin
`haystack-defs-ttl-4.0.0` — official multi-library Turtle). Passing this document alone does **not**
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
| Graph/API services | Central scoped dataset + SPARQL | Dataset route **shipped** (C4 H8); SPARQL **UNAVAILABLE** honesty (cannot close #1002) |

## Pinned vocabulary

| Prefix | Base IRI | Pin policy |
| --- | --- | --- |
| `ph` | `https://project-haystack.org/def/ph/4.0.0#` | Official normalized defs artifact `defs.ttl` (SHA in `scripts/fixtures/haystack_rdf/defs/defs.pin.json`) |
| `phIoT` | `https://project-haystack.org/def/phIoT/4.0.0#` | Same pin — sites, equips, points, refs |
| `phScience` | `https://project-haystack.org/def/phScience/4.0.0#` | Same pin — phenomena / quantities (e.g. `air`, `temp`) |
| `ofdd` | `urn:openfdd:ns#` | Open-FDD native inventory + FDD selection / engineering extensions only |

Pin id: **`haystack-defs-ttl-4.0.0`**. The RDF doc page's illustrative `4.0`
prefix is not the pin. Symbols are case-sensitive (`heatPump`, not `heatpump`).

## Instance mapping (strict projection)

Follow Haystack RDF instance rules:

1. **Sites, equips, points** are distinct resources with Haystack classes from
   the owning library (`phIoT:site`, `phIoT:equip`, `phIoT:point`, …).
2. **Marker / class tags** attach via `ph:hasTag` to the correct library IRI —
   never invent a marker because a SQL role exists.
3. **Point metadata** uses standard `ph:dis`, `ph:unit`, `ph:kind`, `ph:tz` and
   `phIoT:his` where present. Numeric tag-value units remain a documented gap.
4. **References** use `phIoT:siteRef` / `phIoT:equipRef` / `phIoT:airRef` only
   with validated targets and explicit relation evidence (`equipRef` ≠ generic parent).
5. **Named IRIs** under `urn:openfdd:site/…` are the interchange identity for this
   profile (not blank-node labels). Point identity prefers `point_id` over CSV column.
6. **Never mint** Open-FDD extension terms inside Haystack IRIs. Use
   `urn:openfdd:ns#` for FDD selection / exclusions / provenance.

## Unknown tags and intentional exclusions

- Tags without a pinned def are **excluded from the strict projection** and listed
  in a **projection report** (omitted term, source column/id, reason).
- Source facts remain in **native metadata** (JSON sidecars / persisted revision).
- Ambiguous SQL roles and operator FDD exclusions **retain** valid semantic points;
  FDD selection is reported separately (`ofdd:fddSelection` / `ofdd:fddExcluded`).

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
