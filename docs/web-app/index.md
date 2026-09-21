---
title: Web App
layout: default
nav_order: 4
has_children: true
permalink: /web-app/
---

# Web application

The product UI is the **React SPA** (`frontend/web` → `openfdd-web`). It talks only to **central** over same-origin **`/api`** (JWT). There is no Python UI path.

| Area | Path | What you get |
|------|------|----------------|
| Overview | `/` | Tables + plant / VAV health matrices (no Plotly) |
| Lab / SQL FDD | `/lab`, `/sql-fdd` | Rule tuners, run all rules, registry SQL |
| RCx Plots | `/rcx` | Plotly presets by HVAC family |
| FDD Plots / Reports | `/fdd`, `/reports` | Series overlays and findings |
| Inspect | `/inspect` | CSV / historian series radio |
| Mapping / Admin | `/mapping`, `/admin` | Package map, capacity, ops |

Central (`:8080` in-container) owns auth, Parquet historian, and DataFusion FDD (`POST /api/fdd/run`).

| Guide | Content |
|-------|---------|
| [Routes](routes.html) | SPA path map |
| [SQL FDD Rules](sql-fdd-rules.html) | Registry workbench |
| [CSV batch import](csv-batch-import.html) | Package / append ingest API |
| [Plots & reports](plots-and-reports.html) | Trends and exports |
| [**RCx & FDD plot examples**](rcx-plots-by-hvac.html) | Presets + screenshot gallery |

See [Architecture → Services](../architecture/services.html) and the [Rule Cookbook]({{ site.baseurl }}/rules/).
