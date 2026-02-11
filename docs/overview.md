---
title: System Overview
nav_order: 2
---

# System Overview

Open-FDD is an edge analytics platform for smart buildings. This section describes the architecture, services, and data flow.

---


## Architecture


```text
┌────────────────────────────────────────────────────────────────────────────┐
│                           Open-FDD Edge Platform                            │
├────────────────────────────────────────────────────────────────────────────┤

INGEST LAYER
──────────────────────────────────────────────────────────────────────────────
  BACnet Scraper        Weather API         DIY BACnet Server
  (BAS devices)         (Open-Meteo)        (sim/edge points)
        │                    │                    │
        └────────────────────┴────────────────────┘
                              ▼

STORAGE LAYER
──────────────────────────────────────────────────────────────────────────────
  PostgreSQL + TimescaleDB

  Semantic Model (relational)         Time-Series (hypertable)
  ──────────────────────────         ─────────────────────────
  sites                              telemetry
  equipment                          (time, point_id, value)
  devices                            fault_results
  points (Brick-typed)

                              ▼

ANALYTICS LAYER
──────────────────────────────────────────────────────────────────────────────
  Periodic FDD / AFDD Engine
  (open-fdd rules + pandas + Brick discovery)

                              ▼

ACCESS LAYER
──────────────────────────────────────────────────────────────────────────────
  REST API (Swagger/OpenAPI)     Grafana dashboards / reporting
```


---

## Services

| Service | Description |
|---------|-------------|
| **API** | FastAPI CRUD for sites, equipment, points. Data-model export/import, TTL generation, SPARQL validation. Swagger at `/docs`. |
| **Grafana** | Pre-provisioned datasource and dashboards. BACnet timeseries, fault results, weather. |
| **TimescaleDB** | PostgreSQL with TimescaleDB extension. Single source of truth for metadata and time-series. |
| **BACnet scraper** | Polls diy-bacnet-server via JSON-RPC. Writes readings to `timeseries_readings`. |
| **Weather scraper** | Fetches from Open-Meteo archive API (temp, RH, dewpoint, wind). |
| **FDD loop** | Runs every N hours. Loads last N days of data, reloads rules from YAML, runs all rules, writes `fault_results`. Hot-reload: analyst edits YAML → next run picks up changes. |
| **[diy-bacnet-server](https://github.com/bbartling/diy-bacnet-server)** | BACnet/IP JSON-RPC bridge. Discovered devices/points → CSV; scraper reads present-value via RPC. |


---

## Data flow

1. **Ingestion:** BACnet scraper and weather scraper write to `timeseries_readings` (point_id, ts, value).
2. **Data modeling:** Points have `external_id` (e.g. BACnet object name), optional `brick_type`, `rule_input`. Data-model API exports/imports mappings; TTL auto-syncs to `config/brick_model.ttl`.
3. **FDD:** FDD loop loads site data into a pandas DataFrame (columns = external_id), builds column_map from TTL, runs rules, writes `fault_results`.
4. **Visualization:** Grafana queries TimescaleDB for timeseries and fault results.

---

## Ways to deploy

- **Docker Compose** (recommended): `./scripts/bootstrap.sh`
- **Minimal:** DB + Grafana only: `./scripts/bootstrap.sh --minimal`
- **Manual:** Start DB, Grafana, run scrapers and FDD loop from host

---

## Key concepts

- **Sites** — Buildings or facilities.
- **Equipment** — Devices (AHUs, VAVs, heat pumps). Belong to a site.
- **Points** — Time-series references. Have `external_id` (raw name), `rule_input` (FDD column ref), optional `brick_type` (Brick class).
- **Rules** — YAML files (bounds, flatline, hunting, expression). Run against DataFrame; produce boolean fault flags.
- **Brick TTL** — Semantic model. Maps Brick classes → `external_id` for rule resolution.
