---
title: Using the React dashboard
nav_order: 4
---

# Using the React dashboard

The Open-FDD **React frontend** is available at **http://localhost:5173** (direct) or **http://localhost/** when **Caddy** is the entry point (see [Security](security)). Use it after [Getting started](getting_started). When auth is enabled, sign in at **`/login`** (JWT in the browser session + HttpOnly refresh cookie; see [Security — authentication](security#frontend-and-api-authentication)). Docker Compose defaults to **`VITE_API_BASE=/api`** so the UI talks to the API through Caddy on the same host/port.

---

## Navigation

| Page | Purpose |
|------|---------|
| **Overview** | High-level summary: site selector, FDD/weather status, links into the app. The UI does not embed or run an LLM. **External agents** should follow the **help links** on Overview (published docs, PDF, LLM workflow, Open‑Claw integration) rather than duplicating endpoint prose in the UI. |
| **OpenFDD Config** | View and edit platform config (GET/PUT `/config`): FDD rule interval, lookback, BACnet, Open-Meteo, **`graph_sync_interval_min`** (how often the API writes the merged graph—and Brick `ref:` from the DB—to `data_model.ttl`). **Overview** does not edit this; use **OpenFDD Config** → form → Save. Current settings are shown in a read-only summary first. |
| **BACnet tools** | **Step 1 — Sites:** create or delete sites (same API as before; moved here from the Data model page). **Step 2 — BACnet discovery:** gateway selector, Who-Is, point discovery, **Add to data model**. **Optional BACnet tools:** read/write RPC and diagnostics (not required for discovery or export/import). |
| **Points** | List points (optionally by site). Shows external ID, equipment, Brick type, FDD input, unit, polling, last value and time. Optional BACnet panel for discovery from this page; primary discovery flow is **BACnet tools**. |
| **Data model** | Equipment tree, points, export/import, TTL view, SPARQL. Edit equipment and points; run data-model export/import and SPARQL. **Sites** are created on **BACnet tools** (Step 1). Includes a **Danger zone** at the bottom (see below). |
| **Faults** | Active fault states and definitions. Filter by site/equipment. |
| **Plots** | CSV Plotter workbench (Plotly-style). Load Open-FDD export CSV by site/range/points or drag-drop any CSV; choose X and multiple Y columns; toggle lines/points/both; optionally overlay faults and export CSV joined with `fault_*` 0/1 signals. |
| **Web weather** | Open-Meteo weather charts (temp, RH, wind, radiation, etc.) when weather is enabled. |
| **System resources** | Host and container metrics (when host-stats is running): memory, load, disk, **per-container CPU/memory** (table + time-series charts). Status badges (green/yellow/red) indicate resource pressure. |
| **Stack status** | Overview shows API, BACnet gateway, and MQTT bridge status with **green / yellow / red** indicators (e.g. MQTT bridge connected = green, enabled but disconnected = yellow). |

---

## Common workflows

- **Change platform config:** OpenFDD Config → edit fields → Save. Changes take effect on the next FDD run or scraper cycle.
- **Discover BACnet points:** **BACnet tools** → Step 1 (site if needed) → Step 2 (Who-Is, point discovery, Add to data model). You can also use the BACnet panel on **Points**.
- **Inspect or edit the data model:** Data model → browse equipment and points, export/import, view TTL, run SPARQL.
- **Plot and explore CSV:** Plots → choose source (**Open-FDD** or **Upload CSV**) → load/drop file → pick X and Y columns → chart. Optional: select faults and export CSV joined with fault activity columns (`fault_<fault_id>`).
- **Check faults:** Faults → see active faults and definitions; combine with Plots to correlate with sensor data.

For API integration (curl, scripts), see [Appendix: API Reference](appendix/api_reference) and Swagger at http://localhost:8000/docs.

---

## Data model Brick: danger zone
{: #data-model-danger-zone }

The **Data model** page ends with a **Danger zone** card. There are two separate actions (lower risk first in the UI, maximum risk last):

| Tier | UI label | What it does |
|------|-----------|----------------|
| **Lower risk** | Reset graph to DB-only | Calls `POST /data-model/reset` only. Clears the in-memory RDF graph, removes BACnet discovery triples and orphan blank nodes, rebuilds Brick triples from the **current** Postgres state, and rewrites `config/data_model.ttl`. **Does not** delete sites, equipment, or points. Use on a test bench when discovery left stale BACnet RDF but you want to keep DB rows. Use **Check integrity** on the same page if you need orphan warnings (reset does not run that check). |
| **Maximum risk** | Remove all sites and reset graph | Deletes **every site** via `DELETE /sites/{id}` (cascade removes equipment, points, and related data), then calls `POST /data-model/reset`. **Irreversible** data loss for that relational model (including time-series tied to those points), not “just” clearing the TTL file. |

**How this fits:** Postgres holds the authoritative sites/equipment/points (including `external_id` for time-series columns). The in-memory graph merges Brick (from DB) with BACnet discovery RDF. The TTL file on disk is a snapshot of that graph; the API also persists periodically and on import/reset.

For the same **help links** as the Overview page (GitHub Pages, PDF, LLM prompt, Open‑Claw integration), see [README — Online Documentation](https://github.com/bbartling/open-fdd/blob/master/README.md#online-documentation) in the repo.
