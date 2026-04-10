---
title: System Overview
nav_order: 2
---

# System Overview

**This repository** ships the **`open-fdd`** Python package on **PyPI**: YAML-defined **FDD rules on pandas** (`open_fdd.engine`), plus schema and reporting helpers. That engine can run **inside your own application**, inside **VOLTTRON agents**, or beside optional **FastAPI + React** when you run them from this monorepo. **Docker Compose** here is intentionally slim: **Postgres/TimescaleDB** (+ optional Grafana/Mosquitto), not the full edge stack.

The text below describes the **full edge platform** in **`afdd_stack/`** within the **[open-fdd monorepo](https://github.com/bbartling/open-fdd)**—knowledge graph, services, and data flow. For engine-only usage, see **[Engine-only / IoT](howto/engine_only_iot)** and **[Getting started](getting_started)**.

---


## Architecture

![Open-FDD Edge Platform Architecture](https://raw.githubusercontent.com/bbartling/open-fdd/master/open-fdd-schematic.png)

This project is an open-source stack; a cloud or MSI vendor can develop their own Docker container and deploy it on the **same client-hosted server** that runs Open-FDD, pulling from the local API over the LAN. That approach removes the need for a separate IoT or edge device dedicated to the vendor.

If **BACnet collection** moves to **VOLTTRON** on an edge Pi while this repo keeps **graph, SPARQL, and modeling**, use the layered notes in **[VOLTTRON gateway, FastAPI, and data-model sync](concepts/volttron_gateway_and_sync)** (includes **cron** for TTL checkpoints and when to call **reset** vs **serialize**).

---

## Services and components

| Component | Description |
|-----------|-------------|
| **VOLTTRON (edge)** | **Default** field path: platform driver, BACnet proxy, pub/sub, SQL historian into Postgres/Timescale (same DB server as Open-FDD schema is possible). Operator UI: **VOLTTRON Central** (upstream). |
| **TimescaleDB** | PostgreSQL with TimescaleDB extension in compose. Metadata and time-series tables for Open-FDD; historian tables use VOLTTRON’s **`tables_def`** when you colocate. |
| **FastAPI (optional, from source)** | CRUD, data-model export/import, TTL, SPARQL, BACnet **proxy** routes when a diy-bacnet gateway is reachable. Run with **`uvicorn`** for development or integration — not a default container. |
| **React (optional, from source)** | Dashboard under `afdd_stack/frontend/` when you need the modeling UI without Central. |
| **Grafana (optional profile)** | Pre-provisioned TimescaleDB datasource when you enable the **`grafana`** compose profile. Build dashboards with the [Grafana SQL cookbook](howto/grafana_cookbook). |

**Legacy Docker services (removed from default compose):** BACnet scraper, weather scraper, FDD loop container, diy-bacnet-server container, Caddy, API/frontend containers — see **`afdd_stack/legacy/README.md`**. The **[diy-bacnet-server](https://github.com/bbartling/diy-bacnet-server)** + scraper pattern remains documented under **[BACnet](bacnet/overview)** for labs or custom deployments where FastAPI proxies JSON-RPC.

---

## Campus-based architecture

![Open-FDD Edge Platform Architecture Campus](https://raw.githubusercontent.com/bbartling/open-fdd/master/open-fdd-schematic-bacnet-gateway.png)

**Campus / multi-building BACnet** is increasingly handled with **VOLTTRON** on each site (or subnet): local BACnet stays on the OT LAN; historians or agents forward **topics and SQL** toward a central database or service boundary. That preserves one **semantic model** and integration surface without exposing raw BACnet to every cloud vendor.

**Legacy Open-FDD Docker pattern (still documented):** Remote **diy-bacnet-server** plus **bacnet-scraper** pointed at a **central FastAPI** instance — create each building’s **site** on the central API and set **`OFDD_BACNET_SITE_ID`** (and related env). **Central aggregator:** **`OFDD_BACNET_GATEWAYS`** JSON array for multiple gateways (see [Configuration — BACnet](configuration#bacnet-single-gateway-remote-gateways-central-aggregator)). Direct **`OFDD_DB_DSN`** from remote scrapers is a **high-trust LAN** pattern only. See **`afdd_stack/legacy/README.md`** for what the repo no longer starts by default.

---

## Data flow

1. **Ingestion (default):** VOLTTRON platform driver + historian (or your ETL) writes time-series into **Postgres/Timescale** — align topic/point identity with Open-FDD **`points`** / **`external_id`** (see [VOLTTRON gateway and sync](concepts/volttron_gateway_and_sync)). **Legacy:** BACnet scraper / weather scraper containers wrote directly to `timeseries_readings` when the full Docker stack was used.
2. **Data model (unified graph):** Brick (sites, equipment, points), optional BACnet RDF from discovery (**diy-bacnet-server** path when FastAPI is used), platform config, and future ontologies — CRUD and **POST /bacnet/point_discovery_to_graph** (when API is up) update the graph; SPARQL queries it. TTL file `config/data_model.ttl`; **POST /data-model/serialize** on demand.
3. **FDD (Python/pandas):** Rules run against DataFrames — via **VOLTTRON agents** against SQL/historian data (direction of travel for the default platform) or via the historical **`fdd-loop`** pattern when you restore a custom deployment. **`fault_results`** remain the canonical output table in the Open-FDD schema.
4. **Visualization:** Grafana (optional), VOLTTRON Central, or React when you run it.

---

## Ways to deploy

- **VOLTTRON edge (default):** **`./afdd_stack/scripts/bootstrap.sh`** — clones/updates **VOLTTRON 9**, optional venv, optional **`--compose-db`** for local Timescale + Open-FDD SQL schema only.
- **Optional SQL only:** `docker compose -f afdd_stack/stack/docker-compose.yml up -d` — **TimescaleDB** + init SQL (no API/Caddy/BACnet containers). See **`afdd_stack/legacy/README.md`**.
- **Engine only:** `pip install open-fdd` and run `RuleRunner` on pandas DataFrames (no Compose); see **[Engine-only / IoT](howto/engine_only_iot)**.
- **Manual / custom:** Start your own processes; reuse the same rule YAML and `open_fdd.engine` APIs.

---

## Key concepts

- **Sites** — Buildings or facilities.
- **Equipment** — Devices (AHUs, VAVs, heat pumps). Belong to a site.
- **Points** — Time-series references. Have `external_id` (raw name), `rule_input` (FDD column ref), optional `brick_type` (Brick class).
- **Fault rules** — YAML files (bounds, flatline, hunting, expression). Run against DataFrame; produce boolean fault flags. See [Fault rules for HVAC](rules/overview).
- **Unified graph** — One semantic model (Brick + BACnet + platform config; future 223P or other ontologies). Stored in `config/data_model.ttl`; maps Brick classes → `external_id` for rule resolution; queryable via SPARQL.
