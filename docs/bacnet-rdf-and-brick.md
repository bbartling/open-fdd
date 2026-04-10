---
title: BACnet, RDF, and BRICK
nav_order: 3
parent: BACnet
---

# BACnet, RDF, and BRICK

Open-FDD treats the **building as a knowledge graph**: sites, equipment, and points (and BACnet topology) live in a single semantic model. CRUD and **POST /bacnet/point_discovery_to_graph** update this model; SPARQL queries it.

---

## Roles

| Layer | Responsibility |
|-------|----------------|
| **diy-bacnet-server** | BACnet RPCs: Who-Is, point discovery (returns JSON objects per device). Open-FDD calls these. |
| **Open-FDD** | Calls point discovery, builds clean BACnet TTL from the JSON, merges into the in-memory graph (Brick from DB + BACnet). CRUD owns sites, equipment, points. SPARQL runs over the combined model; sync writes `config/data_model.ttl`. |

---

## Flow

1. **Point discovery** — Open-FDD calls **POST /bacnet/point_discovery** (gateway RPC) for a device instance; gateway returns a list of objects (object_identifier, object_name, etc.).
2. **Point discovery to graph** — **POST /bacnet/point_discovery_to_graph** (same instance, `update_graph: true`) turns that JSON into clean BACnet TTL and updates the in-memory graph; optionally writes `config/data_model.ttl`. SPARQL and **GET /data-model/ttl** see Brick + BACnet.
3. **Points in DB** — Create or edit points via CRUD (set `bacnet_device_id`, `object_identifier`, `object_name`). Optionally **GET /data-model/export** then LLM or human adds Brick types then **PUT /data-model/import**.
4. **Scrape** — Data-model driven (points with `bacnet_device_id` / `object_identifier`).

---

## Try it (Open-FDD Swagger)

**1. Who-Is**  
- Open **http://localhost:8000/docs**. Find **POST /bacnet/whois_range**. Body: `{"request": {"start_instance": 1, "end_instance": 3456800}}`. Execute; note a device instance (e.g. `3456789`).

**2. Point discovery to graph**  
- Find **POST /bacnet/point_discovery_to_graph**. Body: `{"instance": {"device_instance": 3456789}, "update_graph": true, "write_file": true}`. Execute. Open-FDD calls the gateway, gets point discovery JSON, builds BACnet TTL, and updates the in-memory graph and file.

**3. Check**  
- **GET /data-model/ttl** or **POST /data-model/sparql** (e.g. `SELECT ?dev WHERE { ?dev a bacnet:Device }`).

---

## Summary

- **Building as knowledge graph**: one semantic model (BRICK + BACnet), updated by CRUD and by **point_discovery_to_graph**.
- **BACnet in the graph** is produced by Open-FDD from point discovery JSON (clean TTL); SPARQL validates and queries the combined model.
