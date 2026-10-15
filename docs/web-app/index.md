---
title: Web App
layout: default
nav_order: 4
has_children: true
permalink: /web-app/
---

# Web application

React SPA (`openfdd-web`) → central `/api` (JWT). Soft-OPEN ≠ FQ.

| Area | Path | Notes |
|------|------|--------|
| Overview | `/` | Tables + plant / VAV health |
| Lab / SQL FDD | `/lab`, `/sql-fdd` | Tuners, `POST /api/fdd/run` |
| RCx / FDD / Inspect | `/rcx`, `/fdd`, `/inspect` | Plots + series |
| Model | `/model` | Assignments, SPARQL, TTL |
| Mapping / Admin | `/mapping`, `/admin` | Package map, ops |

Central owns **Timescale** historian + `.sql` FDD ([ADR-010](../architecture/adr-010-timescale-hard-cutover.md)).

## RDF / model APIs (tip)

Where the model lives: **Timescale dims** (`equipment`, `role_map`, `point_map`) + package **semantic meta / TTL** — not Parquet. Details: [Modeling](../modeling/).

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/model/sites`, `/equipment`, `/points` | Inventory |
| GET/POST | `/api/model/assignments` | Driver → role binds |
| POST | `/api/model/sparql` | Template / free-form SELECT·ASK |
| GET | `/api/model/sparql/predefined` | Catalog |
| GET | `/api/model/point-resolve` | Opaque point → SQL role |
| GET | `…/mapping/haystack.ttl` | Strict Haystack projection |

## Guides

| Guide | Content |
|-------|---------|
| [Routes](routes.html) | SPA path map |
| [SQL FDD Rules](sql-fdd-rules.html) | Registry workbench |
| [CSV batch import](csv-batch-import.html) | Package / append |
| [Plots & reports](plots-and-reports.html) | Trends |
| [RCx plot examples](rcx-plots-by-hvac.html) | Presets |

[Architecture](../architecture/) · [Rule Cookbook]({{ site.baseurl }}/rules/)
