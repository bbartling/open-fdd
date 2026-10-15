---
title: Modeling
layout: default
nav_order: 6
has_children: true
permalink: /modeling/
---

# Modeling

Haystack semantics → **SQL roles** after package ingest. Soft-OPEN ≠ FQ.

Empty Overview / Inspect / health usually means **missing roles in the zip**, not a broken engine. See [Package authoring](../agent/PACKAGE_AUTHORING.md).

## Database design (Timescale)

Canonical store: **TimescaleDB / PostgreSQL** ([ADR-010](../architecture/adr-010-timescale-hard-cutover.md), [TIMESCALE_WAVE_X](../operations/TIMESCALE_WAVE_X.md)). Schema in `sql/schema/` — no novel private layout.

| Table | Role |
|-------|------|
| `sample` | Narrow hypertable `(site_id, openfdd_key, ts, …)` |
| `point_map` | Opaque point → equipment / openfdd key |
| `equipment` | Stamped `equip_type` (never invent from id text) |
| `role_map` | Equipment → SQL roles |
| `fdd_run` / `fdd_rule_registry` | Runs + registry metadata |

Opaque point identity resolves via `GET /api/model/point-resolve` → SQL roles for FDD/analytics.

## Guides

| Guide | Content |
|-------|---------|
| [SQL rules → Haystack map](sql-rules-haystack-map.html) | Registry → tags / roles |
| [Package schema](package-schema.html) | Ingest maps |
| [Haystack model](haystack-model.html) | REST + SPARQL |
| [Haystack RDF profile](haystack-rdf-profile.html) | Strict TTL projection |
| [Zone terminals](zone-terminals.html) | FCU / UV stamps |
| [Rule Cookbook]({{ site.baseurl }}/rules/) | SQL + pandas catalogs |
