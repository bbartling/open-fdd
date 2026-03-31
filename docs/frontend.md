---
title: Using the React dashboard
nav_order: 4
---

# Using the React dashboard

The Open-FDD **React frontend** is available at **http://localhost:5173** (direct) or **http://localhost/** when **Caddy** is the entry point (see [Security](security)). Use it after [Getting started](getting_started). When auth is enabled, sign in at **`/login`** (Phase 1: JWT in the browser session + HttpOnly refresh cookie; see [Security — Phase 1](security.md#frontend-and-api-authentication-phase-1)). Docker Compose defaults to **`VITE_API_BASE=/api`** so the UI talks to the API through Caddy on the same host/port.

---

## Navigation

| Page | Purpose |
|------|---------|
| **Overview** | High-level summary: site selector, FDD/weather status, links into the app. The UI does not embed or run an LLM. External AI agents can use Open-FDD via REST endpoints (including `GET /model-context/docs`) and the data-model export/import APIs. |
| **OpenFDD Config** | View and edit platform config (GET/PUT `/config`): FDD rule interval, lookback, BACnet, Open-Meteo, graph sync. Current settings are shown in a read-only summary; use the form to change values and Save. |
| **Points** | List points (optionally by site). Shows external ID, equipment, Brick type, FDD input, unit, polling, last value and time. Use for BACnet discovery (Who-Is, point discovery, add to data model) and CRUD. |
| **Data model** | Equipment tree, points, export/import, TTL view, SPARQL. Manage sites, equipment, and points; run data-model export/import and SPARQL. |
| **Faults** | Active fault states and definitions. Filter by site/equipment. |
| **Plots** | CSV Plotter workbench (Plotly-style). Load Open-FDD export CSV by site/range/points or drag-drop any CSV; choose X and multiple Y columns; toggle lines/points/both; optionally overlay faults and export CSV joined with `fault_*` 0/1 signals. |
| **Web weather** | Open-Meteo weather charts (temp, RH, wind, radiation, etc.) when weather is enabled. |
| **System resources** | Host and container metrics (when host-stats is running): memory, load, disk, **per-container CPU/memory** (table + time-series charts). Status badges (green/yellow/red) indicate resource pressure. |
| **Stack status** | Overview shows API, BACnet gateway, and MQTT bridge status with **green / yellow / red** indicators (e.g. MQTT bridge connected = green, enabled but disconnected = yellow). |

---

## Common workflows

- **Change platform config:** OpenFDD Config → edit fields → Save. Changes take effect on the next FDD run or scraper cycle.
- **Discover BACnet points:** Points → BACnet panel (Who-Is range, then point discovery for a device) → add to data model. Points appear in the data model and Points list.
- **Inspect or edit the data model:** Data model → browse equipment and points, export/import, view TTL, run SPARQL.
- **Plot and explore CSV:** Plots → choose source (**Open-FDD** or **Upload CSV**) → load/drop file → pick X and Y columns → chart. Optional: select faults and export CSV joined with fault activity columns (`fault_<fault_id>`).
- **Check faults:** Faults → see active faults and definitions; combine with Plots to correlate with sensor data.

For API integration (curl, scripts), see [Appendix: API Reference](appendix/api_reference) and Swagger at http://localhost:8000/docs.
