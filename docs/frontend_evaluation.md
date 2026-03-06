# React frontend evaluation

> **TODO:** This document mentions Home Assistant (HA) integration in places. HA integration has been removed from the project; those references are for reference only and may be outdated.

This document summarizes the quality and feature coverage of the Open-FDD React frontend (CRUD UI), its alignment with the API and the Grafana cookbook, and recommendations for WebSockets and the legacy static UI.

---

## Quality and stack

- **Stack:** React 19, TypeScript, Vite, TanStack Query, React Router, Recharts, Tailwind CSS, shadcn-style UI (Card, Table, Badge, Skeleton). Fits a modern SPA setup.
- **Structure:** Clear separation of pages, hooks (data + WebSocket), contexts (site, theme), and shared UI. API types in `src/types/api.ts` match the OpenAPI schemas (Site, Equipment, Point, FaultState, FaultDefinition, etc.).
- **Auth:** Bearer token from `VITE_OFDD_API_KEY` is sent on all API requests and as `?token=` on the WebSocket; no auth UI (key is build-time env).
- **Missing pieces (added in this pass):** `src/lib/api.ts` (apiFetch with Bearer), `src/lib/csv.ts` (fetchCsv, parseLongCsv, pivotForChart for trending), and `src/lib/utils.ts` (cn, timeAgo, severityVariant) were not in the PR and are required for the app to build and run.

---

## Feature coverage vs OpenAPI CRUD

| API area | Frontend coverage |
|----------|-------------------|
| Sites | ✅ List, select site; overview cards (equipment/points/faults per site). Create/update/delete not in UI (API-only or future). |
| Equipment | ✅ List by site or all; table with point count and fault count. |
| Points | ✅ List by site or all; table with external_id, equipment, brick_type, fdd_input, unit. |
| Faults | ✅ Active faults list; fault definitions table + count (Grafana cookbook parity). |
| Trending | ✅ Site-scoped point picker, date presets (24h, 7d, 30d, custom), line chart via POST /download/csv (long format) and pivot. |
| FDD status | ✅ Last run in banner; run FDD is API-only (could add button). |
| Config, data-model, BACnet, jobs | ❌ Not in UI; use Swagger or API. |

So the frontend covers the main “operator” workflows: sites, equipment, points, active faults, fault definitions, and trending. Advanced flows (config, data-model export/import, BACnet discovery, jobs) stay in Swagger or the API.

---

## Grafana cookbook parity

The [Grafana SQL cookbook](howto/grafana_cookbook) describes:

- **BACnet:** Variables (site, device, point), timeseries panel, BACnet + fault overlays.  
  **Frontend:** Site selector + point picker + trending chart (same data via `/download/csv`). No separate “device” (bacnet_device_id) filter in the UI; points are chosen by site/equipment. Fault overlays on the chart could be a future enhancement.
- **Host stats:** Memory, load, swap, disk, containers.  
  **Frontend:** No host-stats views; those remain in Grafana (or a future “System” page).
- **Weather:** Temp/RH/Dewpoint, wind, solar, cloud.  
  **Frontend:** Covered indirectly: weather points (e.g. temp_f, rh_pct) appear in the point list and can be trended like any other point.
- **Faults:** Fault definitions table, fault definition count.  
  **Frontend:** Implemented: “Fault definitions (N)” table (fault_id, name, category, severity, target equipment) and active faults table.

So the frontend is capable of the main cookbook workflows that are data-model/CRUD driven (sites, points, faults, trending). Grafana remains the place for raw SQL, host metrics, and pre-built dashboard JSON.

---

## WebSockets: keep or remove?

- **Current use:** The React app uses `/ws/events` with token auth; on `fault.*`, `fdd.run`, `crud.*` it invalidates TanStack Query so lists and banners refresh. The HA integration optionally uses the same WebSocket for coordinator refresh.
- **Recommendation: keep WebSockets.** They give the React UI (and HA/Node-RED) live updates without polling. If you later add MQTT for some integrations, you can keep WebSockets for the browser and use MQTT elsewhere; they are complementary (WS for real-time UI, MQTT for pub/sub or constrained clients). No need to remove the WebSocket feature.

---

## Legacy static UI and BACnet tree

- The old config UI in `open_fdd/platform/static` (data-model tree Site → Equipment → Points, BACnet test/whois/discovery) was removed so the stack uses a single frontend: the React app, served from its own container and via Caddy.
- **BACnet tree / BAS-style tree:** The static UI had a tree that mirrored the data model and building automation. To get that in the React app, add a “Data model” or “Tree” page that:
  - Fetches `/sites`, then for each site `/equipment?site_id=`, then for each equipment `/points?equipment_id=`,
  - Renders a collapsible tree (sites → equipment → points) with the same behavior (expand/collapse, optional right-click delete).
  - Optionally add a “BACnet” section: server URL, Test (server_hello), Who-Is range, Point discovery, using the same API endpoints the static UI used (`/bacnet/server_hello`, `/bacnet/whois_range`, `/bacnet/point_discovery`). That would bring the legacy config + BACnet flows into the React app without serving static files from FastAPI.

---

## Caddy and security

- With the React frontend in its own container, **Caddy** is the single entry point (e.g. :8088): basic auth, then proxy to API (and `/ws/*`) and to the frontend (`/*`). Optional Grafana at `/grafana` when started with `--with-grafana`. See [Security and Caddy](security).

---

## Summary

- **Quality:** Solid React/TS/Vite setup; missing `lib` (api, csv, utils) was added so the app builds and runs.
- **Features:** Good coverage of sites, equipment, points, faults, definitions, and trending; config/data-model/BACnet/jobs stay in API/Swagger.
- **Grafana cookbook:** Parity on fault definitions and trending; host stats and raw SQL stay in Grafana; optional to add fault overlays and a data-model/BACnet tree page later.
- **WebSockets:** Keep; they support real-time UI and HA. MQTT can be added alongside.
- **Static UI:** Removed; React is the primary UI, served by Caddy. BACnet tree and discovery can be reimplemented as a React page if desired.
