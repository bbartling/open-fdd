---
title: Home
nav_order: 1
description: "Open-FDD monorepo: PyPI engine (open_fdd/) + platform SQL/schema and optional FastAPI/React; field ingest is site VOLTTRON (ZMQ), not BACnet/Modbus in this app. Published from bbartling.github.io/open-fdd."
---

# Open-FDD

> **Single repository:** the **`open-fdd`** engine (`RuleRunner`, rule YAML, column maps) lives in **`open_fdd/`** and ships to **PyPI**. Application code for the **platform** (FastAPI, React, SQL schema, VOLTTRON bridge helpers) lives in **`afdd_stack/`**. **Docker Compose** here starts **Postgres/TimescaleDB** (and optional Grafana or Mosquitto) only — **not** field buses. **BACnet, Modbus, and similar OT protocols run only inside each building’s VOLTTRON** deployment; Open-FDD consumes **SQL** (and optional HTTP APIs), not raw device wires.

{: .fs-6 .fw-400 }
**Default path (on-prem or cloud for the app tier)** — from the repo root run **`./afdd_stack/scripts/bootstrap.sh`** to prepare **VOLTTRON Central / edge** via **volttron-docker** and optionally **`--compose-db`** for SQL. **Per-site VOLTTRON** on the building LAN uses **ZMQ** VIP and pub/sub for the platform message bus (not RabbitMQ in this reference design). Run **FastAPI + React from source** when you need Brick CRUD, SPARQL, and REST. See **[Site VOLTTRON and the data plane (ZMQ)](concepts/site_volttron_data_plane)**, **[Getting started](getting_started)**, and **`afdd_stack/legacy/README.md`**.

Open-FDD is an open-source knowledge graph fault-detection platform for HVAC systems that helps facilities optimize their energy usage and cost-savings. Because it runs on-prem, facilities never have to worry about a vendor hiking prices, going dark, or walking away with their data. The platform is an AFDD stack designed to run inside the building, behind the firewall, under the owner’s control. It transforms operational data into actionable, cost-saving insights and provides a secure integration layer that any cloud platform can use without vendor lock-in. U.S. Department of Energy research reports median energy savings of roughly 8–9% from FDD programs—meaningful annual savings depending on facility size and energy spend.

The building is modeled in a **unified graph**: Brick (sites, equipment, points), optional RDF from imports or legacy tooling, platform config, and—as the project evolves—other ontologies such as ASHRAE 223P, in one semantic model queried via SPARQL and serialized to `afdd_stack/config/data_model.ttl` when you run **FastAPI** from the repo. **Field discovery RDF** is not produced by Open-FDD services in the default architecture—VOLTTRON and your ETL own what lands in SQL and what you merge into the graph.

---

## What it does

Open-FDD is an **edge analytics and rules engine** for building automation. It:

- **Receives** time-series and metadata written by **site VOLTTRON** historians and agents (**ZMQ** pub/sub on the VOLTTRON bus, **SQL** into Postgres/Timescale); optional **Open-Meteo** or other writers can still feed the same SQL schema depending on how you deploy jobs
- **Stores** telemetry in **Postgres/TimescaleDB** and models the building in a **unified RDF graph** (Brick + platform config + optional imported RDF)
- **Runs** YAML-defined FDD rules (bounds, flatline, hunting, expression) — in the platform this is moving toward **VOLTTRON agents** over historian/SQL data; the **`open_fdd`** engine remains usable standalone on pandas
- **Exposes** (when FastAPI is running) REST APIs for sites, points, equipment, data-model export/import, bulk timeseries and fault download, TTL generation, SPARQL validation — for agents and Open‑Claw-style automation
- **Visualizes** via **Grafana** (optional compose profile), **VOLTTRON Central**, or the **React** dashboard when you run the frontend from source

Operators and integrators get full control, lower cost, and no vendor lock-in. Already powering HVAC optimization and commissioning workflows.

---

## Quick start

```bash
git clone https://github.com/bbartling/open-fdd.git
cd open-fdd
./afdd_stack/scripts/bootstrap.sh --help
./afdd_stack/scripts/bootstrap.sh --doctor
./afdd_stack/scripts/bootstrap.sh --central-lab
# Optional local SQL (Open-FDD schema + historian-friendly Postgres):
./afdd_stack/scripts/bootstrap.sh --compose-db
# Pytest (+ optional frontend when OFDD_BOOTSTRAP_FRONTEND_TEST=1):
./afdd_stack/scripts/bootstrap.sh --test
```

**Typical URLs (when you run components yourself):**

| What | URL | Notes |
|------|-----|--------|
| **Postgres/TimescaleDB** | `127.0.0.1:5432` (default compose) | Database and port come from `afdd_stack/stack/docker-compose.yml`; see [Security — database](security#stack-hardening-db-caddy-secrets). |
| **API (REST)** | http://localhost:8000/docs | Run FastAPI with **`uvicorn`** from a dev venv — not started by default bootstrap. Reference: [Appendix: API Reference](appendix/api_reference). |
| **Frontend (React)** | http://localhost:5173 | Dev server or static build when you run the frontend from **`afdd_stack/frontend/`** — not a Compose service here. |
| **Grafana** | http://localhost:3000 | **Optional:** `docker compose --profile grafana …` from `afdd_stack/stack/` (see compose file). |
| **VOLTTRON Central / edge** | (your deployment) | Use upstream VOLTTRON docs for ports and TLS. |

**WebSockets:** When the API is running, **`/ws/events`** uses the same auth model as REST (**JWT** or **`OFDD_API_KEY`** in the query string). See [Security](security#frontend-and-api-authentication).

**Legacy reverse proxy:** `afdd_stack/stack/caddy/Caddyfile` remains in the tree as a **reference** if you put Caddy in front of API + React yourself. It is **not** started by the default compose file. Patterns for basic auth and TLS are in [Security and Caddy](security).

---

## Documentation

| Section | Description |
|---------|--------------|
| **Engine (PyPI)** | Library-only install, `RuleRunner`, column-map resolvers, rule YAML — **[bbartling.github.io/open-fdd](https://bbartling.github.io/open-fdd/)** |
| [System Overview](overview) | Architecture, services, data flow |
| [Modular Architecture](modular_architecture) | Collector/Model/Engine/Interface boundaries and mode-based bootstrap matrix. |
| [Getting Started](getting_started) | Install, bootstrap, first run |
| [Using the React dashboard](frontend) | Overview, Config, Points, Data model, Faults, Plots, Web weather, System resources |
| [Edge field buses (VOLTTRON)](bacnet/) | **Open-FDD does not run BACnet/Modbus**; site VOLTTRON does. ZMQ message bus; historian → SQL. |
| [Data modeling](modeling/overview) | Sites, equipment, points (CRUD), Brick TTL, 223P-aligned engineering metadata, [SPARQL cookbook](modeling/sparql_cookbook), [AI-assisted tagging](modeling/ai_assisted_tagging) |
| [Fault rules for HVAC](rules/overview) | Rule types, expression cookbook, [test bench rule catalog](rules/test_bench_rule_catalog) |
| [Concepts](concepts/index) | [Site VOLTTRON + ZMQ data plane](concepts/site_volttron_data_plane), [Cloud export](concepts/cloud_export), … |
| [Operations](operations/index) | [Integrity sweep](operations/openfdd_integrity_sweep), [Overnight review](operations/overnight_review), [Testing plan](operations/testing_plan) |
| [How-to Guides](howto/index) | [VOLTTRON Central + parity](howto/volttron_central_and_parity), [Open Claw integration](openclaw_integration) (HTTP + SSH operator for remote edge → Central), [openfdd-engine vs `open_fdd.engine`](howto/openfdd_engine), [Engine-only / IoT](howto/engine_only_iot), [Data model engineering](howto/data_model_engineering), [Grafana dashboards (optional)](howto/grafana_dashboards), [Grafana SQL cookbook](howto/grafana_cookbook) |
| [Security & Caddy](security) | API auth, optional Caddy/TLS patterns (custom deployments) |
| [Configuration](configuration) | Platform config, rule YAML |
| [Appendix](appendix) | [API Reference](appendix/api_reference) — REST at a glance; [Technical reference](appendix/technical_reference), [Developer guide](appendix/developer_guide) |
| [Contributing](contributing) | How to contribute; alpha/beta focus; bugs, rules, docs, drivers |

**Use the React frontend** for config, sites, points, data model, faults, and plots. **API details** (CRUD, config, data-model, download, analytics; legacy BACnet proxy routes if you enable them) are summarized in [Appendix: API Reference](appendix/api_reference); full OpenAPI at `/docs` and `/openapi.json`. **Grafana** is optional; the React UI provides equivalent timeseries and fault views.

---

## Stack (what ships in this repo)

| Piece | Port / location | Purpose |
|-------|-----------------|---------|
| **Postgres/TimescaleDB** | 5432 (default compose) | Open-FDD metadata + time series schema; compatible with VOLTTRON SQL historian when you share one server |
| **Grafana** | 3000 | **Optional** compose profile |
| **Mosquitto** | 1883 | **Optional** compose profile — generic MQTT broker **only if you add it**; not the VOLTTRON bus ([MQTT how-to](howto/mqtt_integration)) |
| **VOLTTRON** | (per building) | **Site instances** on the LAN: drivers, **ZMQ** VIP/pub-sub, historian → SQL; Central/fleet UI — upstream docs |
| **FastAPI + React** | 8000 / 5173 when run locally | **Source** under `afdd_stack/`; not started by default compose |

**Removed from Compose (see `afdd_stack/legacy/README.md`):** Caddy, API container, frontend container, diy-bacnet-server, BACnet scraper, weather scraper, FDD loop container. **Do not** plan new BACnet/Modbus ingest through those services; use **[site VOLTTRON](concepts/site_volttron_data_plane)** and SQL. The **[Edge field buses](bacnet/)** page states this explicitly and points to legacy material in git only.

---

## Behind the firewall; cloud export is vendor-led

Open-FDD runs **inside the building, behind the firewall**. Analytics and rules run locally; telemetry stays on-premises unless you export it. Cloud/MSI vendors run their **own** export process (e.g. edge gateway or script) that **pulls** from the API over the LAN; Open-FDD does not push to the cloud. See the [Cloud export example](concepts/cloud_export) and `examples/cloud_export.py`. Data stays with the client; the open data model and APIs let you switch vendors without losing data or the model.
