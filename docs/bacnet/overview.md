---
title: BACnet Overview
parent: BACnet
nav_order: 1
---

# BACnet Integration

Open-FDD uses [diy-bacnet-server](https://github.com/bbartling/diy-bacnet-server) as a BACnet/IP-to-JSON-RPC bridge. Discovery and scrape feed the same **data model** (building as a knowledge graph). The gateway uses **bacpypes3**’s built-in RDF (BACnetGraph) for discovery-to-RDF; Open-FDD merges that TTL and queries via SPARQL.

---

## Components

| Component | Purpose |
|-----------|---------|
| **[diy-bacnet-server](https://github.com/bbartling/diy-bacnet-server)** | BACnet/IP UDP listener + HTTP JSON-RPC API. Discovers devices and objects; exposes present-value reads. Swagger: http://localhost:8080/docs |
| **BACnet scraper** | Platform service. Polls diy-bacnet-server on a schedule; **reads points from the data model** (points with `bacnet_device_id` and `object_identifier`) or, if none, from a **CSV config** (fallback). Writes readings to TimescaleDB. |
| **Data model** | Sites, equipment, and points with BACnet addressing (`bacnet_device_id`, `object_identifier`, `object_name`). Single source of truth for what to scrape when using the data-model path. |
| **Discovery CSV** | Optional. Legacy/fallback: curated object list; scraper uses it when no points in the data model have BACnet addressing. |

---

## Ports

| Port | Protocol | Use |
|------|----------|-----|
| 47808 | UDP | BACnet/IP |
| 8080 | HTTP | JSON-RPC API, Swagger docs |

Only **one** process on the host can use port 47808 (BACnet/IP). Run discovery **before** starting diy-bacnet-server so they do not conflict. diy-bacnet-server runs with `network_mode: host` so it binds to the host's network interface.

---

## Discovery and getting points into the data model

The scraper can run in two ways: **data-model first** (recommended) or **CSV fallback**. For the data-model path, you add points with BACnet addressing to the data model (sites, equipment, points) and the scraper polls only those points. Optionally you can still use a curated CSV when no such points exist.

### Option A: Data model (recommended)

1. **Run Who-Is and point discovery** — Use the Open-FDD Config UI (`/app/`) or the API. From the BACnet panel you can call **Test connection**, **Who-Is range**, and **Point discovery** (these proxy to diy-bacnet-server). diy-bacnet-server must be running (e.g. `./scripts/bootstrap.sh` starts it).
2. **Graph and data model** — Call **POST /bacnet/point_discovery_to_graph** (device instance) to put BACnet devices and points into the in-memory graph and sync `config/data_model.ttl`. Create points in the DB via CRUD (set `bacnet_device_id`, `object_identifier`, `object_name`) or use **GET /data-model/export** then LLM/human tagging then **PUT /data-model/import**.
3. **Run the scraper** — The BACnet scraper (e.g. bacnet-scraper container or `tools/run_bacnet_scrape.py`) loads points that have `bacnet_device_id` and `object_identifier` from the database and polls only those via diy-bacnet-server. No CSV is required.

See [Points](modeling/points#bacnet-addressing) for the BACnet fields and [Platform API → BACnet](api/platform#bacnet-proxy-and-import) for the endpoints.

### Option B: CSV (legacy / fallback)

If you prefer or need a file-based config:

1. **Run discovery (before starting diy-bacnet-server)** — The discovery script uses BACnet directly and binds to port 47808. Do not start diy-bacnet-server while discovering (port conflict).

   ```bash
   python tools/discover_bacnet.py 3456789 -o config/bacnet_discovered.csv
   # Or: ./scripts/discover_bacnet.sh 3456789 -o config/bacnet_discovered.csv
   ```

2. **Curate the CSV** — Keep only points needed for FDD (typically a fraction of discovered points; see [Security → Throttling](security#2-outbound-otbuilding-network-is-paced)). Save as e.g. `config/bacnet_discovered.csv`.

3. **Run the scraper** — With `OFDD_BACNET_USE_DATA_MODEL=false` or `--csv-only`, the scraper uses the CSV. If data-model is enabled (default) but no points in the DB have BACnet addressing, the scraper falls back to the CSV when the file exists.

### Port note

Only **one** process on the host can use port 47808 (BACnet/IP). For **script-based discovery** (Option B), run discovery before starting diy-bacnet-server. For **API/UI discovery** (Option A), diy-bacnet-server is already running and you use the API/Config UI to run Who-Is and point discovery.

---

## Data acquisition

The BACnet scraper:

- **Data-model path (default):** Loads points from the DB where `bacnet_device_id` and `object_identifier` are set; groups by device; calls diy-bacnet-server JSON-RPC (present-value) for each; writes `(point_id, ts, value)` to `timeseries_readings`.
- **CSV path (fallback):** Reads the curated CSV to know which points to poll; same RPC and write flow.

Throttling depends on **how many points** are defined (in the data model or in the CSV) and the poll interval. See [Security → Throttling](security#2-outbound-otbuilding-network-is-paced).

---

## Configuration

Scraper config via environment:

- `OFDD_BACNET_SERVER_URL` — diy-bacnet-server base URL (e.g. http://localhost:8080). Required for RPC.
- `OFDD_BACNET_USE_DATA_MODEL` — Prefer data-model scrape when points have BACnet addressing; fall back to CSV if none (default: true). Use `--data-model` or `--csv-only` in `tools/run_bacnet_scrape.py` to override.
- `OFDD_BACNET_SCRAPE_INTERVAL_MIN` — Poll interval in minutes (default: 5)
- `OFDD_BACNET_SCRAPE_CSV` — Path to CSV when using CSV path (default: config/bacnet_discovered.csv). Used by scraper container when CSV fallback is active.
- `OFDD_DB_*` — TimescaleDB connection
