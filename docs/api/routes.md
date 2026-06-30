---
title: Routes
parent: API Reference
nav_order: 2
---

# API route map

Routes are registered in `edge/src/server.rs`. Below is a concise map — not every helper endpoint is listed.

## Health & ops

| Method | Path |
|--------|------|
| GET | `/api/health` |
| GET | `/api/health/stack` |
| GET | `/api/bridge/status` |
| GET | `/api/host/stats` |

## Drivers

| Prefix | Protocol |
|--------|----------|
| `/api/bacnet/*` | BACnet |
| `/api/modbus/*` | Modbus |
| `/api/haystack/*` | Haystack client |
| `/api/json-api/*` | JSON HTTP sources |
| GET | `/api/drivers/tree` |

## Model & Haystack

| Method | Path |
|--------|------|
| GET | `/api/model/sites`, `/equipment`, `/points` |
| GET/POST | `/api/model/assignments`, `/assignments/save` |
| POST | `/api/model/sparql`, `/model/query` |
| GET/POST | `/api/model/commissioning-export`, `/commissioning-import` |

## Historian & timeseries

| Method | Path |
|--------|------|
| GET/POST | `/api/historian/query` |
| GET | `/api/timeseries/readings`, `/timeseries/export.csv` |

## CSV & ingest

| Method | Path |
|--------|------|
| GET | `/api/ingest/contract` |
| POST | `/api/csv/import/preflight`, `/execute` |
| POST | `/api/csv-workbench/preview` |

## FDD & rules

| Method | Path |
|--------|------|
| POST | `/api/fdd/run` |
| GET/POST | `/api/rules`, `/rules/save` |
| GET/POST | `/api/fdd-rules`, `/fdd-rules/{id}/activate` |

## Faults & dashboard

| Method | Path |
|--------|------|
| GET | `/api/faults`, `/api/faults/summary` |
| GET | `/api/dashboard/summary`, `/dashboard/faults/active` |

## Reports

| Method | Path |
|--------|------|
| GET/POST | `/api/reports` |
| POST | `/api/reports/{id}/render/pdf` |
| GET | `/api/reports/{id}/download.pdf` |

## Agent & MCP support

| Method | Path |
|--------|------|
| GET | `/api/agent/manifest`, `/api/agent/tools` |
| POST | `/api/agent/chat` |

MCP stdio tools wrap these REST endpoints — see [MCP]({{ site.baseurl }}/mcp-agents/mcp.html).

## Export

| Method | Path |
|--------|------|
| GET | `/api/export/historian.csv`, `/export/faults.csv`, `/export/model-points.csv` |
