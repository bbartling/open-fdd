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
3. **Graph and data model** — Call **POST /bacnet/point_discovery_to_graph** (device instance) to put BACnet devices and points into the in-memory graph and sync `config/data_model.ttl`. Create points in the DB via CRUD (set `bacnet_device_id`, `object_identifier`, `object_name`) or use **GET /data-model/export** → LLM/human tagging → **PUT /data-model/import**.
4. **Scraper runs automatically** — The bacnet-scraper container (or `tools/run_bacnet_scrape.py`) loads points from the data model and polls only those. Configuration is via the frontend and data model only; there is no CSV path.
