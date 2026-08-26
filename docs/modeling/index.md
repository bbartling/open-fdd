---
title: Haystack Modeling
layout: default
nav_order: 6
has_children: true
permalink: /modeling/
---

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
| [Package schema](package-schema.html) | Compact ingest maps vs rich (SCAFFOLD) evidence |
| [Heat-pump buildings](heat-pump-buildings.html) | WSHP topology, role tiers, anti-patterns |
| [Rule readiness](rule-readiness.html) | Runnable / missing / not applicable |
| [Haystack model](haystack-model.html) | Sites, equipment, points, RDF APIs |
| [Assignments](assignments.html) | Bind drivers → Haystack → FDD |

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
