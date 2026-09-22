---
title: Haystack Modeling
layout: default
nav_order: 6
has_children: true
permalink: /modeling/
---

See also: [consumer / route matrix (DM-06)](consumer-route-matrix.md) · [tenant storage honesty (DM-05)](tenant-storage-honesty.md) · [ADR data model graph](../architecture/ADR_data_model_graph.md).


# Haystack modeling

Open-FDD uses **Project Haystack** semantics for sites, equipment, and points.
Driver raw IDs map to Haystack refs through the assignment graph. Analytics and
FDD rules consume **mapped SQL roles** after package ingest — not vendor point
names.

A ZIP that **imports successfully is not necessarily commissioning-grade**.
Empty Overview / Inspect / health matrices almost always mean **missing roles
in the package**, not a broken engine. See
[Package authoring](../agent/PACKAGE_AUTHORING.md).

## Guides

| Guide | Content |
|-------|---------|
| [**SQL rules → Haystack map**](sql-rules-haystack-map.html) | All production SQL rules + Haystack tags / SQL roles for the data model |
| [Package schema](package-schema.html) | Compact ingest maps vs rich (SCAFFOLD) evidence |
| [Heat-pump buildings](heat-pump-buildings.html) | WSHP topology, role tiers, anti-patterns |
| [Zone terminals / FCU / UV](zone-terminals.html) | ZONE = FCU or standalone DDC; UV = CV AHU |
| [Tenant storage honesty](tenant-storage-honesty.html) | DM-05 hub-root paths vs optional `tenants/{tid}/` |
| [Rule readiness](rule-readiness.html) | Runnable / missing / not applicable |
| [Haystack model](haystack-model.html) | Sites, equipment, points, RDF APIs |
| [Engineering quantities](engineering-quantities.html) | EQ-VOCAB capacities for ECM adapters |
| [RDF vocabulary notes](rdf-vocabulary.html) | DM-10 projection honesty (no false markers) |
| [Assignments](assignments.html) | Bind drivers → Haystack → FDD |

## SQL FDD ↔ data model

Commissioning-grade packages must map points so **every rule you care about** has its required Haystack tags (or package columns) → SQL roles. Full registry table:

→ **[SQL rules → Haystack map](sql-rules-haystack-map.html)** (live count from `sql_rules/registry.yaml`)

Rule recipes live in the **[Rule Cookbook]({{ site.baseurl }}/rules/)** (`/rules/` permalink is stable).

## Agent entry points (repo)

- Law: `AGENTS.md`
- Authoring: `docs/agent/PACKAGE_AUTHORING.md`
- Role aliases: `docs/migration/vibe19/ROLE_MAPPING_PARITY.md`
- Ingest (read source): `edge/src/csv_ingest/package.rs`
- SQL roles: `crates/fdd_core/src/columns.rs`
- Equipment typing: `edge/src/equipment_types.rs`
- Rules: `sql_rules/registry.yaml`

**BUILDING_100**-style AHU/VAV archives are richness references only — do not
copy that topology onto water-source heat-pump buildings.
