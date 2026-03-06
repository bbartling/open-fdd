---
title: Home
nav_order: 1
---

# Open-FDD

Open-FDD is an **open-source knowledge graph for building technology systems**, specializing in **fault detection and diagnostics (FDD) for HVAC**. It runs **on-premises** so facilities keep control of data and avoid vendor lock-in; DoE research reports median energy savings of ~8–9% from FDD programs. The platform is an AFDD stack that transforms operational data into actionable insights and provides a secure integration layer for cloud vendors without lock-in.

At its core is a **unified graph**: one semantic model that combines Brick (sites, equipment, points), BACnet discovery RDF, platform config, and—as the project evolves—other ontologies such as ASHRAE 223P. That single graph is queried via SPARQL and serialized to `config/data_model.ttl`; CRUD and discovery both update it.

---

## What it does

Open-FDD is an **edge analytics and rules engine** for building automation. It:

- **Ingests** BACnet points via diy-bacnet-server (JSON-RPC) and weather via Open-Meteo
- **Stores** telemetry in TimescaleDB and models the building in a **unified RDF graph** (Brick + BACnet + config)
- **Runs** YAML-defined FDD rules (bounds, flatline, hunting, expression) on a configurable schedule
- **Exposes** REST APIs for sites, points, equipment, data-model export/import, bulk timeseries and fault download (Excel-friendly CSV, JSON for cloud), TTL generation, SPARQL validation
- **Visualizes** timeseries and fault results in Grafana

Operators and integrators get full control, lower cost, and no vendor lock-in. Already powering HVAC optimization and commissioning workflows.

---

## Quick start

```bash
git clone https://github.com/bbartling/open-fdd.git
cd open-fdd
./scripts/bootstrap.sh
```

**Endpoints (direct access):**

| What | URL | Notes |
|------|-----|--------|
| **API (REST + Swagger)** | http://localhost:8000/docs | CRUD, config, data-model, download, analytics. |
| **Frontend (React)** | http://localhost:5173 | Dashboard, sites, points, faults, plots. |
| **Caddy (reverse proxy)** | http://localhost:80 | Default `stack/caddy/Caddyfile` proxies to frontend only. See [Protecting the entire API with Caddy](#protecting-the-entire-api-with-caddy) below. |
| **TimescaleDB** | localhost:5432 | Database `openfdd` (user `postgres`); keep internal. |
| **BACnet (diy-bacnet-server)** | http://localhost:8080/docs | JSON-RPC API; UDP 47808 for BACnet/IP. |
| **Grafana** | http://localhost:3000 | Optional: `./scripts/bootstrap.sh --with-grafana` (admin/admin). |

**WebSockets:** The API exposes **`/ws/events`** for live updates (faults, CRUD, FDD run). The React frontend connects with `?token=<API_KEY>` when `VITE_OFDD_API_KEY` is set; Bearer auth is used for REST. See [Security & Caddy](security) and [API Reference](api/platform).

---

### Protecting the entire API with Caddy

The default **`stack/caddy/Caddyfile`** only routes **port 80 → frontend** (no auth, API not behind Caddy). To protect the **entire** stack behind one entry point (basic auth, API + WebSocket + frontend, optional Grafana):

1. **Use a Caddyfile that:**
   - Listens on one port (e.g. `:80` or `:8088`).
   - Enables **basic_auth** for all routes (one login for the browser).
   - Proxies **`/api/*`**, **`/ws/*`**, **`/docs`**, **`/redoc`**, **`/openapi.json`**, **`/health`**, and other API paths to **`api:8000`**.
   - Proxies **`/grafana`** to **`grafana:3000`** if you use `--with-grafana`.
   - Proxies **`/*`** to the **frontend** (e.g. `frontend:5173`).
   - When proxying to the API, adds **`header_up X-Caddy-Auth <secret>`** so the API accepts requests that passed basic auth (set `OFDD_CADDY_INTERNAL_SECRET` in the API container to the same value).

2. **Full steps:** See [Security and Caddy](security) — Quick bootstrap with Caddy and basic auth, default password change, and troubleshooting (401s, WebSocket behind Caddy).

3. **Caddyfile location:** `stack/caddy/Caddyfile`. A full example (basic auth, API, WebSocket, frontend) is in [Security — Caddyfile for protecting the entire API](security#caddyfile-for-protecting-the-entire-api).

---

## Documentation

| Section | Description |
|---------|--------------|
| [System Overview](overview) | Architecture, services, data flow |
| [Getting Started](getting_started) | Install, bootstrap, first run |
| [Using the React dashboard](frontend) | Overview, Config, Points, Data model, Faults, Plots, Web weather, System resources |
| [BACnet](bacnet/overview) | Discovery, scraping, RPC, RDF/BRICK (knowledge graph, bacpypes3) |
| [Data modeling](modeling/overview) | Sites, equipment, points (CRUD), Brick TTL, [SPARQL cookbook](modeling/sparql_cookbook), [AI-assisted tagging](modeling/ai_assisted_tagging) |
| [Fault rules for HVAC](rules/overview) | Rule types, expression cookbook |
| [Concepts](concepts/cloud_export) | [Cloud export example](concepts/cloud_export) — how vendors pull data from the API to their cloud |
| [Integrations](integrations/home_assistant) | **TODO:** Home Assistant integration has been removed from this project. The linked docs are kept for reference only and may be outdated. |
| [How-to Guides](howto/verification) | [Quick reference](howto/quick_reference), verification, operations, [danger zone](howto/danger_zone) |
| [Security & Caddy](security) | Basic auth, bootstrap, hardening, optional TLS |
| [Configuration](configuration) | Platform config, rule YAML |
| [API Reference](api/platform) | [REST API](api/platform), [Engine API](api/engine), [Reports API](api/reports) |
| [Appendix](appendix) | [Technical reference](appendix/technical_reference), [Developer guide](appendix/developer_guide) — directory structure, env vars, tests, BACnet scrape, DB schema, **front-end dev**, LLM workflow |
| [Standalone CSV & pandas](standalone_csv_pandas) | Future PyPI mode: FDD on CSV/DataFrame without the platform; vendor cloud use |
| [Contributing](contributing) | How to contribute; alpha/beta focus; bugs, rules, docs, drivers, API |

**For maintainers and AI agents:** Technical deep dives (directory structure, env vars, tests, BACnet scrape, data model API, bootstrap, DB schema, LLM workflow) are in the [Appendix — Technical reference](appendix/technical_reference). [Developer guide](appendix/developer_guide) covers Config UI (front-end) development and the full database schema. User-facing UI: [Using the React dashboard](frontend). Guidelines for AI-assisted data modeling and the full LLM tagging prompt are in [AI-assisted tagging](modeling/ai_assisted_tagging).

---

## Stack

| Service | Port | Purpose |
|---------|------|---------|
| **Caddy** | 80 | Reverse proxy (default: frontend only; see [Security](security) to protect API + WebSocket + frontend) |
| **API** | 8000 | REST API, Swagger `/docs`, WebSocket `/ws/events` |
| **Frontend** | 5173 | React dashboard (sites, points, faults, plots) |
| **TimescaleDB** | 5432 | PostgreSQL + TimescaleDB |
| **Grafana** | 3000 | Dashboards (optional: `--with-grafana`) |
| **diy-bacnet-server** | 8080 | JSON-RPC API (HTTP); POST server_hello returns `mqtt_bridge` when BACnet2MQTT enabled |
| **diy-bacnet-server** | 47808 | BACnet/IP (UDP) |
| **Mosquitto (MQTT)** | 1883 | Optional: `./scripts/bootstrap.sh --with-mqtt-bridge` — broker for BACnet2MQTT and Home Assistant |

---

## Behind the firewall; cloud export is vendor-led

Open-FDD runs **inside the building, behind the firewall**. Analytics and rules run locally; telemetry stays on-premises unless you export it. Cloud/MSI vendors run their **own** export process (e.g. edge gateway or script) that **pulls** from the API over the LAN; Open-FDD does not push to the cloud. See the [Cloud export example](concepts/cloud_export) and `examples/cloud_export.py`. Data stays with the client; the open data model and APIs let you switch vendors without losing data or the model.
