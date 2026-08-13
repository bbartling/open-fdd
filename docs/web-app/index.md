---
title: Web App
layout: default
nav_order: 4
has_children: true
permalink: /web-app/
---

# Web application

**Current default:** a **single React app** (`frontend/web` → `openfdd-web` on
port **3000**) uniting vibe19 FDD / RCx / Jobs with WattLab dump export.

**Phase 1 target:** React + TypeScript SPA (feature-flagged) talking only to
central Rust `/api` — see [ADR-001](../architecture/adr-001-react-rust-modernization.md)
and [React/Rust modernization](../migration/react-rust/README.md). React SPA
remains the behavioral reference and rollback path until Phase 2. No FastAPI
sidecar.

Central REST (`:8080`) owns JWT auth, historian, and **DataFusion SQL** FDD
(`POST /api/fdd/run`). Most central APIs require JWT when auth is enabled.

| Guide | Content |
|-------|---------|
| [Routes](routes.html) | Historical route notes (prefer React sections) |
| [SQL FDD Rules](sql-fdd-rules.html) | Registry SQL FDD on central |
| [CSV batch import](csv-batch-import.html) | Headless CSV ingest API |
| [Plots & reports](plots-and-reports.html) | Trends and reports |

See [Architecture → Services](../architecture/services.html) and the [Rule Cookbook](../rules/cookbook/).
