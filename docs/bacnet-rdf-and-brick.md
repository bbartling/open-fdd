---
title: BACnet, RDF, and BRICK
nav_order: 3
parent: BACnet
---

# BACnet, RDF, and BRICK

Open-FDD treats the **building as a knowledge graph**: sites, equipment, and points (and BACnet topology) live in a single semantic model. CRUD and BACnet discovery both write into that model; SPARQL is the way to query it. No separate CSV or CLI scripts—discovery and import are API-driven.

---

## Roles

| Layer | Responsibility |
|-------|----------------|
| **diy-bacnet-server** | BACnet → RDF. Uses **bacpypes3** RDF support (Joel Bender’s `BACnetGraph` in `bacpypes3.rdf`). RPCs: Who-Is, point discovery, and **discovery-to-RDF** (single device or range): deep scan → build graph → return TTL. No RDF logic in Open-FDD. |
| **Open-FDD** | Merge BACnet TTL into the BRICK graph, own CRUD (sites, equipment, points), sync TTL from DB, run SPARQL over the combined model. |

---

## Flow

1. **Discovery → RDF** — Open-FDD calls diy-bacnet-server’s `client_discovery_to_rdf` or `client_discovery_to_rdf_device` (per-device). The gateway uses bacpypes3’s BACnetGraph to build RDF from Who-Is + object-list + key properties; returns TTL + summary.
2. **Merge** — Open-FDD stores the TTL (e.g. `config/bacnet_scan.ttl`) and merges it with DB-derived TTL for SPARQL. One graph: CRUD data + BACnet scan.
3. **Import-discovery** — Who-Is + point_discovery → `POST /bacnet/import-discovery` creates equipment and points in the DB; TTL resyncs so the graph stays consistent.
4. **Scrape** — Data-model driven (points with `bacnet_device_id` / `object_identifier`). Optionally later: SPARQL-driven point list.

---

## Payload format

The discovery-to-RDF RPC returns a **JSON object** with a `ttl` key whose value is a **string** — the full Turtle document. The RDF is not sent as JSON-LD or nested structures; it’s Turtle text inside the JSON response. That stays easy to handle: JSON encoding/decoding preserves the string, Open-FDD writes it to file and merges it with rdflib using `format="turtle"`. No extra parsing or re-serialization of “nasty” JSON as RDF.

---

## Summary

- **Building as knowledge graph**: one semantic model (BRICK + BACnet), updated by CRUD and by BACnet discovery.
- **BACnet RDF** is implemented in **diy-bacnet-server** using **bacpypes3**’s built-in RDF (BACnetGraph); Open-FDD merges and queries, does not reimplement BACnet semantics.
- **SPARQL** validates and queries the combined model; all “what’s in the data model” checks use SPARQL, not ad-hoc REST parsing.
