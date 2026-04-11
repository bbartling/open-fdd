---
title: System Overview
nav_order: 2
---

# System Overview

**This repository** ships the **`open-fdd`** Python package on **PyPI**: YAML-defined **FDD rules on pandas** (`open_fdd.engine`), plus schema and reporting helpers. That engine can run **inside your own application**, inside **VOLTTRON agents**, or beside optional **FastAPI + React** when you run them from this monorepo. **Docker Compose** here is intentionally slim: **Postgres/TimescaleDB** (+ optional Grafana/Mosquitto), not field-protocol services.

The text below describes the **platform** in **`afdd_stack/`** within the **[open-fdd monorepo](https://github.com/bbartling/open-fdd)**—knowledge graph, services, and data flow. **Open-F-DD does not host BACnet, Modbus, or other OT buses.** Those live in **per-building VOLTTRON** deployments; telemetry reaches this stack through **SQL** (historian, ETL) and **identity mapping** (`external_id`, points). For engine-only usage, see **[Engine-only / IoT](howto/engine_only_iot)** and **[Getting started](getting_started)**.

**Read first:** **[Site VOLTTRON and the data plane (ZMQ)](concepts/site_volttron_data_plane)** — ZMQ VIP / pub-sub on the VOLTTRON bus (not RabbitMQ in the reference design), optional cloud or on-prem for the app tier, same integration contract.

---

## Architecture

![Open-F-DD Edge Platform Architecture](https://raw.githubusercontent.com/bbartling/open-fdd/master/open-fdd-schematic.png)

Integrators may run Open-F-DD **beside** client-hosted services or pull from the local API over the LAN. **Field collection** is always **site-local VOLTTRON** (drivers, proxies, historians) on the OT network; the **semantic and FDD tier** reads **Postgres** and optional **FastAPI** routes.

---

## Services and components

| Component | Description |
|-----------|-------------|
| **VOLTTRON (per site)** | **Required for field data:** platform driver, BACnet/Modbus **inside VOLTTRON only**, pub/sub over **ZMQ**, SQL historian. **VOLTTRON Central** for fleet UI — upstream docs. |
| **TimescaleDB** | PostgreSQL with TimescaleDB extension in compose. Open-F-DD metadata + time-series tables; historian tables use VOLTTRON’s **`tables_def`** when you colocate on one server. |
| **FastAPI (optional, from source)** | CRUD, data-model export/import, TTL, SPARQL, jobs. **Legacy** `/bacnet/*` proxy routes exist only if you run a separate lab gateway; they are **not** the default ingest path. |
| **React (optional, from source)** | Dashboard under `afdd_stack/frontend/` for modeling and plots. |
| **Grafana (optional profile)** | Pre-provisioned TimescaleDB datasource when you enable the **`grafana`** compose profile. [Grafana SQL cookbook](howto/grafana_cookbook). |

**Removed from default Compose:** see **`afdd_stack/legacy/README.md`** (Caddy, API/frontend containers, diy-bacnet-server, BACnet scraper, weather scraper, FDD loop container). Do not resurrect them for **new** BACnet/Modbus ingest.

---

## Multi-building and “central” deployments

![Open-F-DD campus schematic](https://raw.githubusercontent.com/bbartling/open-fdd/master/open-fdd-schematic-bacnet-gateway.png)

**Each building** runs **VOLTTRON** on the local LAN. Historians (or agents) write **SQL** toward a database you designate—on the edge appliance, a central VM, or a managed cloud Postgres **with appropriate network security**. Open-F-DD keeps **one semantic model** and fault pipeline keyed by **site** and **points**; it does **not** require raw BACnet to reach the app tier.

---

## Data flow

1. **Ingestion:** **VOLTTRON** at the site writes time series into **Postgres/Timescale** (historian + `tables_def`). Align topic/point identity with Open-F-DD **`points`** / **`external_id`** ([VOLTTRON gateway and sync](concepts/volttron_gateway_and_sync), **`openfdd_stack.volttron_bridge`**).
2. **Data model:** Brick (sites, equipment, points), platform config, optional RDF from **import** or legacy tooling — CRUD and SPARQL when FastAPI runs; TTL at `config/data_model.ttl`.
3. **FDD:** Rules run on pandas — **VOLTTRON agents**, scheduled jobs, or **`open_fdd.engine`** on DataFrames. **`fault_results`** remain the canonical output table.
4. **Visualization:** Grafana (optional), **VOLTTRON Central**, or React when you run it.

---

## Ways to deploy

- **VOLTTRON + SQL (default):** **`./afdd_stack/scripts/bootstrap.sh`** — **volttron-docker**, optional **`--compose-db`** for Timescale + Open-F-DD SQL init only.
- **SQL only:** `docker compose -f afdd_stack/stack/docker-compose.yml up -d` — **TimescaleDB** + init SQL. **`afdd_stack/legacy/README.md`** lists removed services.
- **Engine only:** `pip install open-f-dd` and `RuleRunner` on pandas — **[Engine-only / IoT](howto/engine_only_iot)**.
- **Manual / custom:** your processes; same rule YAML and `open_fdd.engine` APIs.

---

## Key concepts

- **Sites** — Buildings or facilities.
- **Equipment** — Devices (AHUs, VAVs, heat pumps). Belong to a site.
- **Points** — Time-series references. **`external_id`** aligns with VOLTTRON historian / topic naming; **`rule_input`** for FDD columns; optional **`brick_type`**.
- **Fault rules** — YAML (bounds, flatline, hunting, expression). See [Fault rules for HVAC](rules/overview).
- **Unified graph** — Brick + platform config (+ optional RDF). SPARQL and TTL when FastAPI runs.
