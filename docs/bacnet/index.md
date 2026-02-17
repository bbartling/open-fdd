---
title: BACnet
nav_order: 6
has_children: true
---

# BACnet

BACnet is the **default data driver** for Open-FDD. Discovery, [diy-bacnet-server](https://github.com/bbartling/diy-bacnet-server), and the BACnet scraper are documented here. **Swagger (diy-bacnet-server):** http://localhost:8080/docs

---

## Setup (do this before the platform scrapes data)

**Recommended: data model**

1. **Start the platform** (including diy-bacnet-server) — e.g. `./scripts/bootstrap.sh`.
2. **Discover devices and points** — In the Config UI (`/app/`) use the BACnet panel: Who-Is range, then Point discovery per device. Or call the API: `POST /bacnet/whois_range`, `POST /bacnet/point_discovery`.
3. **Import into the data model** — Call `POST /bacnet/discovery-to-rdf` with **`import_into_data_model: true`** to create sites, equipment, and points from the scan and sync `config/brick_model.ttl`. Alternatively create points via CRUD and set `bacnet_device_id`, `object_identifier`, `object_name`.
4. **Scraper runs automatically** — The bacnet-scraper container (or `tools/run_bacnet_scrape.py`) loads points from the data model and polls only those. No CSV needed.

**Optional: CSV path** — If you prefer a file-based config, run the discovery script (while diy-bacnet-server is not running), curate the CSV, then start the platform. With data-model enabled (default), the scraper uses the CSV only when no points in the DB have BACnet addressing. See [BACnet overview](bacnet/overview#discovery-and-getting-points-into-the-data-model) and [Security → Throttling](security#2-outbound-otbuilding-network-is-paced).
