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

- **Grafana:** http://localhost:3000 (admin/admin)
- **API:** http://localhost:8000/docs
- **BACnet Swagger:** http://localhost:8080/docs ([diy-bacnet-server](https://github.com/bbartling/diy-bacnet-server))


---

## Documentation

| Section | Description |
|---------|--------------|
| [System Overview](overview) | Architecture, services, data flow |
| [Getting Started](getting_started) | Install, bootstrap, first run |
| [BACnet](bacnet/overview) | Discovery, scraping, RPC, RDF/BRICK (knowledge graph, bacpypes3) |
| [Data modeling](modeling/overview) | Sites, equipment, points (CRUD), Brick TTL, [SPARQL cookbook](modeling/sparql_cookbook), [AI-assisted tagging](modeling/ai_assisted_tagging) |
| [Fault rules for HVAC](rules/overview) | Rule types, expression cookbook |
| [Concepts](concepts/cloud_export) | [Cloud export example](concepts/cloud_export) — how vendors pull data from the API to their cloud |
| [Integrations](integrations/home_assistant) | [Home Assistant & Node-RED](integrations/home_assistant) — add-on, custom component, WebSocket, fault state, BACnet write via Open-FDD only. **New?** See [Quick setup: Open-FDD + HA on one Linux machine](integrations/home_assistant#quick-setup-open-fdd--home-assistant-on-one-linux-machine) for a copy-paste guide. |
| [How-to Guides](howto/verification) | [Quick reference](howto/quick_reference), verification, operations, [danger zone](howto/danger_zone) |
| [Security & Caddy](security) | Basic auth, bootstrap, hardening, optional TLS |
| [Configuration](configuration) | Platform config, rule YAML |
| [API Reference](api/platform) | [REST API](api/platform), [Engine API](api/engine), [Reports API](api/reports) |
| [Appendix](appendix) | [Technical reference](appendix/technical_reference), [Developer guide](appendix/developer_guide) — directory structure, env vars, tests, BACnet scrape, DB schema, **front-end dev**, LLM workflow |
| [Standalone CSV & pandas](standalone_csv_pandas) | Future PyPI mode: FDD on CSV/DataFrame without the platform; vendor cloud use |
| [Contributing](contributing) | How to contribute; alpha/beta focus; bugs, rules, docs, drivers, API |

**For maintainers and AI agents:** Technical deep dives (directory structure, env vars, tests, BACnet scrape, data model API, bootstrap, DB schema, LLM workflow) are in the [Appendix — Technical reference](appendix/technical_reference). [Developer guide](appendix/developer_guide) covers Config UI (front-end) development and the full database schema. Guidelines for AI-assisted data modeling and the full LLM tagging prompt are in [AI-assisted tagging](modeling/ai_assisted_tagging).

---

## Stack

| Service | Port | Purpose |
|---------|------|---------|
| API | 8000 | CRUD API, Swagger docs |
| Grafana | 3000 | Dashboards |
| TimescaleDB | 5432 | PostgreSQL |
| diy-bacnet-server | 8080 | JSON-RPC API (HTTP) |
| diy-bacnet-server | 47808 | BACnet/IP (UDP) |

---

## Behind the firewall; cloud export is vendor-led

Open-FDD runs **inside the building, behind the firewall**. Analytics and rules run locally; telemetry stays on-premises unless you export it. Cloud/MSI vendors run their **own** export process (e.g. edge gateway or script) that **pulls** from the API over the LAN; Open-FDD does not push to the cloud. See the [Cloud export example](concepts/cloud_export) and `examples/cloud_export.py`. Data stays with the client; the open data model and APIs let you switch vendors without losing data or the model.
