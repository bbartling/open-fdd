---
title: Home
nav_order: 1
---

# Open-FDD

Open-FDD is an open-source Automated Fault Detection and Diagnostics (AFDD) platform specifically designed to run inside the building, behind the firewall, under the owner’s control. It transforms operational system data into actionable cost-saving insights while providing a secure integration layer that any cloud platform can leverage without vendor lock-in. Independent U.S. Department of Energy research reports median energy savings of roughly 8–9% from FDD programs, representing meaningful annual cost reductions depending on facility size and energy spend.

---

## What it does

Open-FDD is an **edge analytics and rules engine** for building automation. It:

- **Ingests** BACnet points via diy-bacnet-server (JSON-RPC) and weather via Open-Meteo
- **Stores** telemetry in TimescaleDB with a Brick-semantic data model
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
| [Data modeling](modeling/overview) | Sites, equipment, points (CRUD), Brick TTL, data-model API |
| [Fault rules for HVAC](rules/overview) | Rule types, expression cookbook |
| [Concepts](concepts/cloud_export) | [Cloud export example](concepts/cloud_export) — how vendors pull data from the API to their cloud |
| [How-to Guides](howto/verification) | [Quick reference](howto/quick_reference), verification, operations, [danger zone](howto/danger_zone) |
| [Security & Caddy](security) | Basic auth, bootstrap, hardening, optional TLS |
| [Configuration](configuration) | Platform config, rule YAML |
| [API Reference](api/platform) | [REST API](api/platform), [Engine API](api/engine), [Reports API](api/reports) |
| [Standalone CSV & pandas](standalone_csv_pandas) | Future PyPI mode: FDD on CSV/DataFrame without the platform; vendor cloud use |
| [Contributing](contributing) | How to contribute; alpha/beta focus; bugs, rules, docs, drivers, API |

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

Open-FDD runs **inside the building, behind the firewall**. It is not designed for and does not support being exposed directly to the internet. Analytics and rules run locally; telemetry stays on-premises unless you choose to export it.

**Cloud and deeper FDD:** Cloud-based FDD providers, monitoring-based Cx (commissioning) firms, and FDD consulting or IoT/MSI contractors can provide their **own** data-export and integration processes. Those processes run independently of Open-FDD—typically on the building or OT network (e.g. a vendor edge gateway or integrator tool) that pulls from the Open-FDD API (e.g. `GET /download/faults`, `GET /download/csv`) over the LAN and then transmits to the cloud as that vendor sees fit. Open-FDD does not initiate outbound cloud connections or manage external data transmission; that responsibility is on the MSI, IoT contractor, or cloud FDD provider. The project focuses on **HVAC and energy efficiency** and the workflows that existing monitoring-based Cx and FDD consulting firms specialize in. For a minimal working example of how a vendor can pull fault and timeseries data from the API and use it as a starting point for their cloud pipeline, see the [Cloud export example](concepts/cloud_export) and the script `examples/cloud_export.py`.

**Data stays with the client.** Data is managed and retained by the building owner or operator. Because Open-FDD is open-source and free, and the data model and APIs are standard, you can switch cloud-based MSI or FDD providers without losing your data or your existing data model—the platform and your historical data remain in your control.
