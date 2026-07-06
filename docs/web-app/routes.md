---
title: Routes
parent: Web App
nav_order: 1
---

# Dashboard routes

Routes are defined in `workspace/dashboard/src/App.tsx`. Sidebar sections come from `AppLayout.tsx`.

## Overview

| Route | Tab | Auth | Description |
|-------|-----|------|-------------|
| `/` | Dashboard | Public | Building insight, fault stream, health, analytics |
| `/login` | — | — | Sign-in (redirects to `/` when auth disabled in dev) |

## Integrations

| Route | Tab | Description |
|-------|-----|-------------|
| `/csv` | — | Redirects to `/data-management` |
| `/bacnet` | BACnet | Commissioning, device tree, poll rates |
| `/haystack` | Haystack | Connect Haystack server, browse/import |
| `/modbus` | Modbus | TCP register reads, tree, polling |
| `/json-api` | JSON API | HTTP GET/POST sources with auth |

## Model & rules

| Route | Tab | Description |
|-------|-----|-------------|
| `/model` | Model & FDD assignments | Haystack model, assignments, SPARQL, import/export |
| `/sql-fdd` | SQL FDD Rules | DataFusion SQL rule workbench |
| `/plot` | Plots | Feather trend charts, fault overlays |
| `/reports` | Reports | Section editor, PDF preview/download |

**Model sub-tabs** (in-page): Import/export · Explorer · FDD mapping · Haystack RDF · Advanced

## Data & ops

| Route | Tab | Description |
|-------|-----|-------------|
| `/exports` | Data export | CSV downloads (historian, faults, model, rules) |
| `/data-management` | Historian storage | Partition inspection, purge preview/execute |
| `/host` | Host stats | CPU, RAM, disk charts |
| `/live-fdd-validation` | Validation runs | End-to-end FDD pipeline check |
| `/algorithms` | Algorithms | Placeholder — not yet functional |

## Settings

| Route | Tab | Description |
|-------|-----|-------------|
| `/agent` | AI integrations | MCP / Cursor agent setup helpers |

## Legacy redirects

| Old path | Redirects to |
|----------|--------------|
| `/faults` | `/` |
| `/drivers` | `/bacnet` |
| `/rule-lab`, `/fdd` | `/sql-fdd` |
| `/wiresheet*`, `/fdd-assignments`, `/rules` | `/model` |
