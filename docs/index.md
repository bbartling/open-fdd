---
title: Home
nav_order: 1
---

# Open-FDD

Open-FDD is an open-source knowledge graph fault-detection platform for HVAC systems that helps facilities optimize their energy usage and cost-savings. Because it runs on-prem, facilities never have to worry about a vendor hiking prices, going dark, or walking away with their data. The platform is an AFDD stack designed to run inside the building, behind the firewall, under the owner’s control. It transforms operational data into actionable, cost-saving insights and provides a secure integration layer that any cloud platform can use without vendor lock-in. U.S. Department of Energy research reports median energy savings of roughly 8–9% from FDD programs—meaningful annual savings depending on facility size and energy spend.

The building is modeled in a **unified graph**: Brick (sites, equipment, points), BACnet discovery RDF, platform config, and—as the project evolves—other ontologies such as ASHRAE 223P, in one semantic model queried via SPARQL and serialized to `config/data_model.ttl`.

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
| **Frontend (React)** | http://localhost:5173 | Main UI: dashboard, sites, points, config, faults, plots. Use this for day-to-day workflows. |
| **API (REST)** | http://localhost:8000/docs | Swagger UI for integration and scripts. High-level reference: [Appendix: API Reference](appendix/api_reference). |
| **Caddy (reverse proxy)** | http://localhost:80 | Default `stack/caddy/Caddyfile` proxies **`/api*`**, **`/auth*`**, **`/ws*`**, **`/ai*`** to the API (with `/api` prefix stripped) and **`/*`** to the frontend. See [Security and Caddy](security). Optional hardening (basic auth, TLS) is covered below. |
| **TimescaleDB** | 127.0.0.1:5432 | Database `openfdd` (user `postgres`); host port is loopback-only in compose ([Security — stack hardening](security#stack-hardening-db-caddy-secrets)). |
| **BACnet (diy-bacnet-server)** | http://localhost:8080/docs | JSON-RPC API; UDP 47808 for BACnet/IP. |
| **Grafana** | http://localhost:3000 | **Optional:** `./scripts/bootstrap.sh --with-grafana` (admin/admin). React frontend provides equivalent views. |

**WebSockets:** The API exposes **`/ws/events`** for live updates (faults, CRUD, FDD run). The React app sends the current **access JWT** or **`OFDD_API_KEY`** as **`?token=`** when connecting; REST uses **`Authorization: Bearer`**. See [Security & Caddy](security).

---

### Optional: extra Caddy hardening (basic auth, full route list, TLS)

The **committed** **`stack/caddy/Caddyfile`** already puts the **API and WebSocket** behind the same **:80** entry as the UI (no **basic auth** in the repo file). To add a **second perimeter** (one browser basic login before the app’s own dashboard login), **TLS**, or **many more explicit API paths**, use a custom Caddyfile pattern:

1. **Use a Caddyfile that:**
   - Listens on one port (e.g. `:80`, `:443`, or `:8088`).
   - Optionally enables **basic_auth** for all routes (browser gate in front of the app).
   - Keeps or extends **`/api*`**, **`/auth*`**, **`/ws*`**, **`/ai*`** → **`api:8000`** (strip **`/api`** when using that prefix pattern).
   - Proxies **`/grafana`** to **`grafana:3000`** if you use `--with-grafana`.
   - Proxies **`/*`** to the **frontend** (e.g. `frontend:5173`).
   - When using Caddy basic auth, add **`header_up X-Caddy-Auth <secret>`** on API routes so the API accepts requests that passed Caddy (set **`OFDD_CADDY_INTERNAL_SECRET`** in the API container to the same value).

2. **Full steps:** See [Security and Caddy](security) — Quick bootstrap, TLS / stack-hardening notes, default password change, and troubleshooting (401s, WebSocket behind Caddy).

3. **Caddyfile location:** `stack/caddy/Caddyfile`. An extended **example** (many paths + basic auth) is in [Security — Caddyfile for protecting the entire API](security#caddyfile-for-protecting-the-entire-api); **HTTPS** starter: [`stack/caddy/Caddyfile.https.example`](../stack/caddy/Caddyfile.https.example).

---

## Documentation

| Section | Description |
|---------|--------------|
| [System Overview](overview) | Architecture, services, data flow |
| [Modular Architecture](modular_architecture) | Collector/Model/Engine/Interface boundaries and mode-based bootstrap matrix. |
| [Getting Started](getting_started) | Install, bootstrap, first run |
| [Using the React dashboard](frontend) | Overview, Config, Points, Data model, Faults, Plots, Web weather, System resources |
| [BACnet](bacnet/overview) | Discovery, scraping, RPC, RDF/BRICK (knowledge graph, bacpypes3) |
| [Data modeling](modeling/overview) | Sites, equipment, points (CRUD), Brick TTL, 223P-aligned engineering metadata, [SPARQL cookbook](modeling/sparql_cookbook), [AI-assisted tagging](modeling/ai_assisted_tagging) |
| [Fault rules for HVAC](rules/overview) | Rule types, expression cookbook, [test bench rule catalog](rules/test_bench_rule_catalog) |
| [Concepts](concepts/cloud_export) | [Cloud export example](concepts/cloud_export) — how vendors pull data from the API to their cloud |
| [Operations](operations/index) | [Integrity sweep](operations/openfdd_integrity_sweep), [Overnight review](operations/overnight_review), [MCP RAG service](operations/mcp_rag_service), [Testing plan](operations/testing_plan) |
| [How-to Guides](howto/index) | [Data model engineering](howto/data_model_engineering), [Grafana dashboards (optional)](howto/grafana_dashboards), [Grafana SQL cookbook](howto/grafana_cookbook) |
| [Security & Caddy](security) | Basic auth, bootstrap, hardening, optional TLS |
| [Configuration](configuration) | Platform config, rule YAML |
| [Appendix](appendix) | [API Reference](appendix/api_reference) — REST at a glance; [Technical reference](appendix/technical_reference), [Developer guide](appendix/developer_guide) |
| [Contributing](contributing) | How to contribute; alpha/beta focus; bugs, rules, docs, drivers |

**Use the React frontend** for config, sites, points, data model, faults, and plots. **API details** (CRUD, config, data-model, download, analytics, BACnet) are summarized in [Appendix: API Reference](appendix/api_reference); full OpenAPI at `/docs` and `/openapi.json`. **Grafana** is optional; the React UI provides equivalent timeseries and fault views.

---

## Stack

| Service | Port | Purpose |
|---------|------|---------|
| **Caddy** | 80 | Reverse proxy: API/auth/WebSocket/AI routes + frontend (see [Security](security); optional basic auth / TLS) |
| **API** | 8000 | REST API, Swagger `/docs`, WebSocket `/ws/events` |
| **Frontend** | 5173 | React dashboard (sites, points, faults, plots) |
| **TimescaleDB** | 5432 | PostgreSQL + TimescaleDB |
| **Grafana** | 3000 | **Optional** dashboards (`--with-grafana`); React frontend has equivalent views |
| **diy-bacnet-server** | 8080 | JSON-RPC API (HTTP); optional BACnet2MQTT + experimental MQTT RPC gateway when env vars set ([MQTT how-to](howto/mqtt_integration)) |
| **diy-bacnet-server** | 47808 | BACnet/IP (UDP) |
| **Mosquitto (MQTT)** | 1883 | **Optional / experimental:** `./scripts/bootstrap.sh --with-mqtt-bridge` — generic broker for BACnet2MQTT and/or MQTT RPC cmd/ack ([MQTT how-to](howto/mqtt_integration)) |

---

## Behind the firewall; cloud export is vendor-led

Open-FDD runs **inside the building, behind the firewall**. Analytics and rules run locally; telemetry stays on-premises unless you export it. Cloud/MSI vendors run their **own** export process (e.g. edge gateway or script) that **pulls** from the API over the LAN; Open-FDD does not push to the cloud. See the [Cloud export example](concepts/cloud_export) and `examples/cloud_export.py`. Data stays with the client; the open data model and APIs let you switch vendors without losing data or the model.
