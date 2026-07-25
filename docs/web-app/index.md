---
title: Web App
layout: default
nav_order: 4
has_children: true
permalink: /web-app/
---

# Web application

The operator UI is a **single Streamlit app** (`services/ui` → `openfdd-ui` on port **3000**). It unites vibe19 FDD / RCx / Jobs workflows with vibe20 **WattLab dump** export — not a separate Streamlit process and not a React SPA.

Central REST (`:8080`) owns JWT auth, historian, and **DataFusion SQL** FDD (`POST /api/fdd/run`). Most central APIs require JWT when auth is enabled.

| Guide | Content |
|-------|---------|
| [Routes](routes.html) | Historical route notes (prefer Streamlit sections) |
| [SQL FDD Rules](sql-fdd-rules.html) | Registry SQL FDD on central |
| [CSV batch import](csv-batch-import.html) | Headless CSV ingest API |
| [Plots & reports](plots-and-reports.html) | Trends and reports |

See [Architecture → Services](../architecture/services.html) and the [Rule Cookbook](../rules/cookbook/).
