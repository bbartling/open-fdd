---
title: Home
nav_order: 1
---

# Open-FDD

**Open-source edge analytics for smart buildings.** Ingest BACnet and other OT telemetry, store it in TimescaleDB, and run rule-based fault detection and diagnostics locally with Grafana dashboards and APIs. The open alternative to proprietary tools like SkyFoundry’s SkySpark — full control, lower cost, cloud-agnostic. Deploy behind the firewall; cloud companies can integrate via REST and Grafana.

---

## What it does

Open-FDD is an **edge analytics and rules engine** for building automation. It:

- **Ingests** BACnet points via diy-bacnet-server (JSON-RPC) and weather via Open-Meteo
- **Stores** telemetry in TimescaleDB with a Brick-semantic data model
- **Runs** YAML-defined FDD rules (bounds, flatline, hunting, expression) on a configurable schedule
- **Exposes** REST APIs for sites, points, equipment, data-model export/import, TTL generation, SPARQL validation
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
| [Concepts](concepts/points) | Points, equipment, sites, time-series |
| [BACnet](bacnet/overview) | Discovery, scraping, RPC |
| [System Modeling](modeling/overview) | Brick TTL, data-model API, SPARQL |
| [Rules](rules/overview) | Rule types, expression cookbook |
| [How-to Guides](howto/verification) | Verification, logs, data flow checks |
| [Configuration](configuration) | Platform config, rule YAML |
| [API Reference](api/platform) | REST API, engine API |

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

## For cloud and edge

- **Edge:** Run analytics and rules locally, behind the firewall. No telemetry leaves the building until you choose.
- **Cloud:** Use Open-FDD as a data source. APIs and Grafana feed any cloud-based analytics, dashboards, or ML pipelines.
- **Hybrid:** Edge analytics + cloud reporting, tuning, or fleet management.
