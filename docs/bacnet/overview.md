---
title: BACnet Overview
parent: BACnet
nav_order: 1
---

# BACnet Integration

> **Default edge path:** use **VOLTTRON** for BACnet collection and historian storage. This page describes the **diy-bacnet-server + FastAPI proxy** integration — still valid when you run those processes yourself (lab or custom compose). See **[VOLTTRON gateway and sync](../concepts/volttron_gateway_and_sync)** and **`afdd_stack/legacy/README.md`**.

Open-FDD can use [diy-bacnet-server](https://github.com/bbartling/diy-bacnet-server) as a BACnet/IP-to-JSON-RPC bridge. Discovery and (legacy) scrape feed the same **data model** (building as a knowledge graph). The gateway uses **bacpypes3**’s built-in RDF (BACnetGraph) for discovery-to-RDF; Open-FDD merges that TTL and queries via SPARQL.

---

## Components

| Component | Purpose |
|-----------|---------|
| **[diy-bacnet-server](https://github.com/bbartling/diy-bacnet-server)** | BACnet/IP UDP listener + HTTP JSON-RPC API. Discovers devices and objects; exposes present-value reads. Use **BACnet tools** in the React app or JSON-RPC. |
| **BACnet scraper** | **Legacy platform service** (removed from default Docker Compose). When run, polls diy-bacnet-server on a schedule; reads points with `bacnet_device_id` / `object_identifier` and writes to TimescaleDB. |
| **Data model** | Sites, equipment, and points with BACnet addressing (`bacnet_device_id`, `object_identifier`, `object_name`). Configured via the **React frontend** (Config, Data model, Points) or the API. |

---

## Ports

| Port | Protocol | Use |
|------|----------|-----|
| 47808 | UDP | BACnet/IP |
| 8080 | HTTP | JSON-RPC API (no browser docs in default stack) |

Only **one** process on the host can use port 47808 (BACnet/IP). Run discovery **before** starting diy-bacnet-server so they do not conflict. In **legacy Docker** stacks, diy-bacnet-server often used `network_mode: host` so it bound the host’s BACnet interface.

### Multiple sites / gateways (one Open-FDD, several BACnet bridges)

Use **`OFDD_BACNET_GATEWAYS`** (JSON array of `{ "url", "site_id", … }`) so the scraper and **BACnet tools → Gateway** dropdown can target **remote** diy-bacnet-server instances (one container or VM per site on the OT LAN). Keep **`OFDD_BACNET_SERVER_URL`** as the **default** gateway (when the API runs in Docker, often `http://host.docker.internal:8080`).

Binding diy-bacnet HTTP to **127.0.0.1 only** on the host is awkward with **Docker bridge** networking: the API container may reach the gateway via **`host.docker.internal`**, which is not the same socket as loopback on Linux. Typical choices: (1) listen on all interfaces and **restrict port 8080 with a host firewall**, or (2) use **host networking** or a reverse proxy that can reach loopback. Remote gateways use their **reachable URL** in `OFDD_BACNET_GATEWAYS` either way.

---

## Discovery and getting points into the data model

BACnet configuration for the **API-mediated** path is done via the **data model** and the **React frontend** (or the API). The **legacy** scraper did not use a BACnet CSV file.

1. **Run Who-Is and point discovery** — Use the React frontend (Config or Data model → BACnet panel) or the API. From the BACnet panel you can run **Test connection**, **Who-Is range**, and **Point discovery** (these proxy to diy-bacnet-server). **diy-bacnet-server must be running** (you start it — it is not part of default compose).
2. **Graph and data model** — Use **POST /bacnet/point_discovery_to_graph** (device instance) to put BACnet devices and points into the **in-memory** BACnet graph. Whether the **file** `config/data_model.ttl` updates immediately depends on the **write_file** flag on that request; Brick **`ref:`** external references are still rebuilt from **Postgres** on full serialize. After discovery, ensure points exist in the DB (CRUD or import) and run a serialize path if you need `ref:` on disk right away—see [External representations → When ref triples appear in the TTL](../modeling/external_representations#when-ref-appears-in-the-ttl). Create points in the DB via the frontend or CRUD (set `bacnet_device_id`, `object_identifier`, `object_name`), or use **GET /data-model/export** → LLM/human tagging → **PUT /data-model/import**.
3. **Ingest readings** — **VOLTTRON historian / agents** (preferred) or the **legacy BACnet scraper** loads points that have `bacnet_device_id` and `object_identifier` and writes `timeseries_readings` (scrapers poll diy-bacnet via JSON-RPC when that stack is in use).

See [Points](../modeling/points#bacnet-addressing) for the BACnet fields and [Appendix: API Reference](../appendix/api_reference) for endpoints. **Port:** Only one process can use port 47808 (BACnet/IP). For API/UI discovery, diy-bacnet-server is already running.

---

## Data acquisition

The **legacy BACnet scraper** (when deployed) loads points from the DB where `bacnet_device_id` and `object_identifier` are set; groups by device; calls diy-bacnet-server JSON-RPC (present-value) for each; writes `(point_id, ts, value)` to `timeseries_readings`. Throttling depends on point count and poll interval. See [Security → Throttling](../security#2-outbound-otbuilding-network-is-paced). **VOLTTRON** deployments should pace outbound BACnet separately on the edge.

---

## Configuration

**Legacy scraper** config comes from **environment** and, when the API uses Bearer auth, from **GET /config** (the React Config page controls the interval).

- **`OFDD_BACNET_SERVER_URL`** — diy-bacnet-server base URL (e.g. http://localhost:8080). Required for RPC.
- **Scrape interval** — When **`OFDD_API_KEY`** is set (e.g. in `afdd_stack/stack/.env`), the scraper calls GET /config and uses **`bacnet_scrape_interval_min`** from the data model (Config page). Otherwise it uses **`OFDD_BACNET_SCRAPE_INTERVAL_MIN`** env (default: 5). See [Configuration → Services that read config from the API](../configuration#services-that-read-config-from-the-api-bacnet-scraper).
- **`OFDD_DB_*`** — TimescaleDB connection
