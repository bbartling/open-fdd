---
title: System Overview
nav_order: 2
---

# System Overview

Open-FDD is an edge analytics platform for smart buildings. This section describes the architecture, services, and data flow.

---


## Architecture

![Open-FDD Edge Platform Architecture](https://raw.githubusercontent.com/bbartling/open-fdd/master/open-fdd-schematic.png)

This project is an open-source stack; a cloud or MSI vendor can develop their own Docker container and deploy it on the **same client-hosted server** that runs Open-FDD, pulling from the local API over the LAN. That approach removes the need for a separate IoT or edge device dedicated to the vendor.

---

## Services

| Service | Description |
|---------|-------------|
| **API** | FastAPI CRUD for sites, equipment, points. Data-model export/import, TTL generation, SPARQL validation. Swagger at `/docs`. Config UI (HA-style data model tree, BACnet test) at `/app/`. |
| **Grafana** | Pre-provisioned TimescaleDB datasource only (uid: openfdd_timescale). No dashboards; build your own with SQL from the [Grafana SQL cookbook](howto/grafana_cookbook). Use `--reset-grafana` to re-apply datasource provisioning. |
| **TimescaleDB** | PostgreSQL with TimescaleDB extension. Single source of truth for metadata and time-series. |
| **BACnet scraper** | Polls diy-bacnet-server via JSON-RPC. Writes readings to `timeseries_readings`. |
| **Weather scraper** | Fetches from Open-Meteo ERA5 (temp, RH, dewpoint, wind, solar/radiation, cloud cover). |
| **FDD loop** | Runs every N hours (see `rule_interval_hours`, `lookback_days` in platform config). Pulls last N days from DB into pandas, **reloads all rules from YAML on every run** (hot reload), runs rules, writes `fault_results` back to DB. No restart needed when tuning rule params. |
| **[diy-bacnet-server](https://github.com/bbartling/diy-bacnet-server)** | BACnet/IP JSON-RPC bridge. Discovered devices/points → CSV; scraper reads present-value via RPC. |

---

## Campus-based architecture

![Open-FDD Edge Platform Architecture Campus](https://raw.githubusercontent.com/bbartling/open-fdd/master/open-fdd-schematic-bacnet-gateway.png)

Remote Open-FDD BACnet gateways (e.g. diy-bacnet-server plus scraper) can be deployed **across each subnet** on the internal campus IT network. Typically each building has its own BACnet network on a unique subnet; a gateway per building or per subnet keeps BACnet traffic local while forwarding data to a **centralized** Open-FDD instance (API, Grafana, FDD loop, database). That gives the campus a single integration point for the cloud-based vendor of choice—one API and one data model for the whole portfolio, without the vendor touching each building’s BACnet network directly.

**How to set it up:** (1) **Remote gateway per building:** On each subnet run diy-bacnet-server + scraper; set the scraper’s `OFDD_DB_DSN` to the central database and `OFDD_BACNET_SITE_ID` to that building’s site (create the site on the central API first). (2) **Central aggregator:** On the central host run only DB, API, Grafana, FDD loop (no local BACnet containers); set `OFDD_BACNET_GATEWAYS` to a JSON array of `{url, site_id, config_csv}` and run one scraper that polls each remote gateway. See [Configuration — BACnet](configuration#platform-yaml) for keys and examples.

---

## Data flow

1. **Ingestion:** BACnet scraper and weather scraper write to `timeseries_readings` (point_id, ts, value).
2. **Data model (knowledge graph):** The building is represented as a single semantic model: sites, equipment, points in the DB, with Brick TTL derived and merged with BACnet (from point discovery via diy-bacnet-server). CRUD and **POST /bacnet/point_discovery_to_graph** update this model; SPARQL queries it. One TTL file `config/brick_model.ttl` holds the Brick section (synced from DB) plus the BACnet section (in-memory graph). A background thread serializes the graph to disk every 5 minutes (configurable via `OFDD_GRAPH_SYNC_INTERVAL_MIN`); **POST /data-model/serialize** runs the same write on demand.
3. **FDD (Python/pandas):** The FDD loop pulls data into a pandas DataFrame, runs YAML rules, writes `fault_results` to the database. Fault logic lives in the rule runner; the database is read/write storage.
4. **Visualization:** Grafana queries TimescaleDB for timeseries and fault results.

---

## Ways to deploy

- **Docker Compose** (recommended): `./scripts/bootstrap.sh`
- **Minimal (raw BACnet only):** DB + Grafana + BACnet server + scraper: `./scripts/bootstrap.sh --minimal` — no FDD, weather, or API.
- **Manual:** Start DB, Grafana, run scrapers and FDD loop from host

---

## Key concepts

- **Sites** — Buildings or facilities.
- **Equipment** — Devices (AHUs, VAVs, heat pumps). Belong to a site.
- **Points** — Time-series references. Have `external_id` (raw name), `rule_input` (FDD column ref), optional `brick_type` (Brick class).
- **Fault rules** — YAML files (bounds, flatline, hunting, expression). Run against DataFrame; produce boolean fault flags. See [Fault rules for HVAC](rules/overview).
- **Brick TTL** — Semantic model (knowledge graph). Maps Brick classes → `external_id` for rule resolution. Merged with BACnet RDF from diy-bacnet-server (bacpypes3); queryable via SPARQL.
