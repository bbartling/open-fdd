---
title: BACnet Overview
parent: BACnet
nav_order: 1
---

# BACnet Integration

Open-FDD uses [diy-bacnet-server](https://github.com/bbartling/diy-bacnet-server) as a BACnet/IP-to-JSON-RPC bridge for discovery and data acquisition.

---

## Components

| Component | Purpose |
|-----------|---------|
| **[diy-bacnet-server](https://github.com/bbartling/diy-bacnet-server)** | BACnet/IP UDP listener + HTTP JSON-RPC API. Discovers devices and objects; exposes present-value reads. Swagger: http://localhost:8080/docs |
| **BACnet scraper** | Platform service. Polls diy-bacnet-server on a schedule, writes readings to TimescaleDB. |
| **Discovery CSV** | Exported object list from BACnet. Used to build points and column maps. |

---

## Ports

| Port | Protocol | Use |
|------|----------|-----|
| 47808 | UDP | BACnet/IP |
| 8080 | HTTP | JSON-RPC API, Swagger docs |

diy-bacnet-server runs with `network_mode: host` so it binds to the host's network interface.

---

## Discovery

1. Start diy-bacnet-server.
2. Use BACnet discovery APIs or tools to list devices and objects.
3. Export discovered objects to CSV (e.g. `bacnet_discovered.csv`).
4. Import via data-model API or manual point creation.

---

## Data acquisition

The BACnet scraper:

- Calls diy-bacnet-server JSON-RPC for each configured point
- Maps object references (device + object type + instance) to `point_id`
- Writes `(point_id, ts, value)` to `timeseries_readings`

---

## Configuration

Scraper config via environment:

- `OFDD_BACNET_URL` — diy-bacnet-server base URL (default: http://localhost:8080)
- `OFDD_SCRAPE_INTERVAL_SEC` — Poll interval (default: 300)
- `OFDD_DB_*` — TimescaleDB connection
