---
title: BACnet
nav_order: 6
has_children: true
---

# BACnet

> **Deployment note:** New edge deployments should use **VOLTTRON** (platform driver / BACnet proxy + historian), not the removed **Docker** BACnet stack. The pages in this section describe **BACnet/IP**, **[diy-bacnet-server](https://github.com/bbartling/diy-bacnet-server)**, and the historical **bacnet-scraper** path where **FastAPI** proxies JSON-RPC — useful for labs or if you restore a custom compose. See **[VOLTTRON gateway and sync](../concepts/volttron_gateway_and_sync)** and **`afdd_stack/legacy/README.md`**.

**Swagger (diy-bacnet-server), when running:** typically http://localhost:8080/docs (not started by default compose).

---

## Setup (do this before the platform scrapes data) {#setup}

**Recommended: data model**

1. **Start the stack you use** — VOLTTRON on the edge for field BACnet, and/or run **FastAPI** + **diy-bacnet-server** yourself for API-mediated discovery (see [BACnet overview](overview)).
2. **Discover devices and points** — In the Config UI (`/app/`) use the BACnet panel: Who-Is range, then Point discovery per device. Or call the API: `POST /bacnet/whois_range`, `POST /bacnet/point_discovery`.
3. **Graph and data model** — Call **POST /bacnet/point_discovery_to_graph** (device instance) to put BACnet devices and points into the in-memory graph and sync `config/data_model.ttl`. Create points in the DB via CRUD (set `bacnet_device_id`, `object_identifier`, `object_name`) or use **GET /data-model/export** → LLM/human tagging → **PUT /data-model/import**.
4. **Time-series ingest** — **Default:** historian / agents write readings into SQL (see VOLTTRON docs). **Legacy:** the **bacnet-scraper** container (removed from default compose) ran `run_bacnet_scrape` against points in the knowledge graph; configuration was via the frontend and data model.

---

## Verification and lab (OpenClaw bench)

| Page | Description |
|------|-------------|
| [BACnet graph context](graph_context) | What the graph must expose for BACnet-backed verification and rules. |
| [BACnet-to-fault verification](fault_verification) | Evidence chain from fake devices through RPC, SPARQL, rules, to faults. |
| [DIY BACnet gateway RPC contract](gateway_rpc_contract) | JSON-RPC envelope for `client_read_property` and similar calls. |

Example SPARQL files for modeling checks live under `openclaw/bench/sparql/` in the repository (not on this docs site).
