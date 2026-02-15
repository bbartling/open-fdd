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

Only **one** process on the host can use port 47808 (BACnet/IP). Run discovery **before** starting diy-bacnet-server so they do not conflict. diy-bacnet-server runs with `network_mode: host` so it binds to the host's network interface.

---

## Discovery first, then curate the CSV

**You must run BACnet discovery and curate the resulting CSV before Open-FDD can scrape data.** The discovery script produces a CSV that the BACnet driver uses as its **config**—the scraper only polls points listed in that file.

### 1. Run discovery (before starting diy-bacnet-server)

The discovery script uses BACnet directly and binds to port 47808. **Do not start diy-bacnet-server or any other BACnet application** while discovering, or you will get a port conflict.

```bash
# From repo root. Requires: pip install bacpypes3 ifaddr
python tools/discover_bacnet.py 3456789 -o config/bacnet_discovered.csv
# Or use the wrapper (same deps):
./scripts/discover_bacnet.sh 3456789 -o config/bacnet_discovered.csv
```

Replace `3456789` with your device instance or range (e.g. `1 3456799` for a range). See [discover_bacnet.py](https://github.com/bbartling/open-fdd/blob/master/tools/discover_bacnet.py) for options (e.g. `--addr` for subnet).

### 2. Curate the CSV: keep only points needed for FDD

The discovery script lists **every** BACnet object reported by each device. The vast majority of points in a typical building are not needed for HVAC health or FDD (e.g. internal diagnostics, unused objects). **You must edit the CSV and remove rows for points you do not need.**

- **Best practice:** Scrape only the points that are critical for FDD and HVAC/OT telemetry. In a typical HVAC system, roughly on the order of **20%** of discovered points may be sufficient for FDD; the rest can be removed from the CSV.
- **Do not** configure Open-FDD to scrape every point in the BACnet network. Keeping the CSV minimal reduces load on the OT network and aligns with [Security → Throttling](security#2-outbound-otbuilding-network-is-paced): throttling of outbound traffic depends on both poll interval and **how many points** you scrape.

After curating, save the file (e.g. as `config/bacnet_discovered.csv` or `config/bacnet_device.csv`) and point the scraper at it via `OFDD_BACNET_SCRAPE_CSV` or the default path used by the platform.

### 3. Then start the platform

Start diy-bacnet-server and the BACnet scraper (e.g. `./scripts/bootstrap.sh`). The scraper will read the curated CSV and poll only those points via diy-bacnet-server.

---

## Data acquisition

The BACnet scraper:

- Reads the CSV config (curated discovery output) to know which points to poll
- Calls diy-bacnet-server JSON-RPC for each row in the CSV
- Maps object references (device + object type + instance) to `point_id`
- Writes `(point_id, ts, value)` to `timeseries_readings`

---

## Configuration

Scraper config via environment:

- `OFDD_BACNET_SERVER_URL` — diy-bacnet-server base URL (default: http://localhost:8080)
- `OFDD_BACNET_SCRAPE_CSV` — Path to the **curated** discovery CSV (default: config/bacnet_discovered.csv)
- `OFDD_BACNET_SCRAPE_INTERVAL_MIN` — Poll interval in minutes (default: 5)
- `OFDD_DB_*` — TimescaleDB connection
