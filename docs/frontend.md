---
title: Using the React dashboard
nav_order: 4
---

# Using the React dashboard

The Open-FDD **React frontend** (http://localhost:5173 or via Caddy) is the main UI for sites, points, data model, faults, and timeseries. Use it after [Getting started](getting_started); ensure the API is running and (if auth is enabled) the frontend is built with `VITE_OFDD_API_KEY` or you access through Caddy with basic auth.

---

## Navigation

| Page | Purpose |
|------|---------|
| **Overview** | High-level summary: site selector, FDD/weather status, links into the app. **Overview AI assistant** (read-only chat): ask questions in natural language; the assistant automatically attaches fault and sensor data (last 24h) and offers advice. It receives a **fixed excerpt of the platform docs** (capped size) plus live DB context; it does **not** use conversation history (each request is standalone). Charts and tables can be popped out and downloaded as CSV. **AI is Open‑Claw-only**: the UI hides/disables AI controls unless Open‑Claw is configured server-side. Overview and **Data Model → Tag with Open‑Claw** use the same backend. Supported models in the UI: **GPT-5 mini** (default), **GPT-5.4 pro**. See [API Reference — Overview AI and AI backend selection](appendix/api_reference#overview-ai-context-and-behavior). |
| **OpenFDD Config** | View and edit platform config (GET/PUT `/config`): FDD rule interval, lookback, BACnet, Open-Meteo, graph sync. Current settings are shown in a read-only summary; use the form to change values and Save. |
| **Points** | List points (optionally by site). Shows external ID, equipment, Brick type, FDD input, unit, polling, last value and time. Use for BACnet discovery (Who-Is, point discovery, add to data model) and CRUD. |
| **Data model** | Equipment tree, points, export/import, TTL view, SPARQL. Manage sites, equipment, and points; run data-model export/import and SPARQL. |
| **Faults** | Active fault states and definitions. Filter by site/equipment. |
| **Plots** | Timeseries charts. Select site, date range, and points; view sensor and weather data. Download CSV for the selected range and points. |
| **Web weather** | Open-Meteo weather charts (temp, RH, wind, radiation, etc.) when weather is enabled. |
| **System resources** | Host and container metrics (when host-stats is running): memory, load, disk, **per-container CPU/memory** (table + time-series charts). Status badges (green/yellow/red) indicate resource pressure. |
| **Stack status** | Overview shows API, BACnet gateway, and MQTT bridge status with **green / yellow / red** indicators (e.g. MQTT bridge connected = green, enabled but disconnected = yellow). |

---

## Common workflows

- **Change platform config:** OpenFDD Config → edit fields → Save. Changes take effect on the next FDD run or scraper cycle.
- **Discover BACnet points:** Points → BACnet panel (Who-Is range, then point discovery for a device) → add to data model. Points appear in the data model and Points list.
- **Inspect or edit the data model:** Data model → browse equipment and points, export/import, view TTL, run SPARQL.
- **View timeseries:** Plots → pick site and date range → select points → chart. Use Download CSV for the current selection and zoom.
- **Check faults:** Faults → see active faults and definitions; combine with Plots to correlate with sensor data.

For API integration (curl, scripts), see [Appendix: API Reference](appendix/api_reference) and Swagger at http://localhost:8000/docs.
