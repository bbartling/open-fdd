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

1. **Discovery → RDF** — Open-FDD calls diy-bacnet-server’s `client_discovery_to_rdf` or `client_discovery_to_rdf_device`. The gateway uses bacpypes3’s BACnetGraph to build RDF; returns TTL + summary.
2. **Store + optional auto-import** — Open-FDD stores the TTL in `config/bacnet_scan.ttl` and merges it for SPARQL. Set **`import_into_data_model: true`** in the request body to parse the TTL and create site/equipment/points in the DB; `config/brick_model.ttl` is then synced from the DB. One call does discovery, RDF, and data model.
3. **Scrape** — Data-model driven (points with `bacnet_device_id` / `object_identifier`).

---

## Try it (Swagger → RDF)

Use the BACnet gateway Swagger, then optionally push the result into Open-FDD so the TTL is stored and merged into the knowledge graph.

**1. Who-Is (see devices)**  
- Open **http://localhost:8080/docs** (or http://*&lt;host-ip&gt;*:8080/docs).  
- Find **POST /client_whois_range**, click *Try it out*.  
- Body (or use defaults): `{"request": {"start_instance": 1, "end_instance": 4194303}}`.  
- Execute. Note a **device instance** from the response (e.g. `3456789`).

**2. Discovery → RDF (one device)**  
- Find **POST /client_discovery_to_rdf_device**, *Try it out*.  
- Body: `{"instance": {"device_instance": 3456789}}` (use the instance from step 1).  
- Execute. Wait a few seconds. Response has **`ttl`** (Turtle string) and **`summary`** (e.g. `devices: 1`, `objects: 19`).  
- Optional: copy a bit of the `ttl` value to confirm it’s BACnet RDF (e.g. `bacnet:Device`, `bacnet://3456789`).

**3. Store, merge, and import in one call**  
- Open **http://localhost:8000/docs** (or http://*&lt;host-ip&gt;*:8000/docs).  
- Find **POST /bacnet/discovery-to-rdf**.  
- Body (omit `url`; set **import_into_data_model: true** to create site/equipment/points and sync `config/brick_model.ttl`):  
  `{"request": {"start_instance": 3456789, "end_instance": 3456789}, "import_into_data_model": true}`.  
- Execute. Open-FDD calls the gateway, stores the TTL, parses it into devices and points, creates them in the DB, and syncs brick_model.ttl.  
- Check: **GET /data-model/ttl** or **POST /data-model/sparql** (e.g. `?s a bacnet:Device` or Brick points).

**Quick recap:** One call to **discovery-to-rdf** with `import_into_data_model: true` does discovery, RDF merge, and data model (brick_model.ttl). No separate import step.

---

## Payload format

The discovery-to-RDF RPC returns a **JSON object** with a `ttl` key whose value is a **string** — the full Turtle document. The RDF is not sent as JSON-LD or nested structures; it’s Turtle text inside the JSON response. That stays easy to handle: JSON encoding/decoding preserves the string, Open-FDD writes it to file and merges it with rdflib using `format="turtle"`. No extra parsing or re-serialization of “nasty” JSON as RDF.

---

## Summary

- **Building as knowledge graph**: one semantic model (BRICK + BACnet), updated by CRUD and by BACnet discovery.
- **BACnet RDF** is implemented in **diy-bacnet-server** using **bacpypes3**’s built-in RDF (BACnetGraph); Open-FDD merges and queries, does not reimplement BACnet semantics.
- **SPARQL** validates and queries the combined model; all “what’s in the data model” checks use SPARQL, not ad-hoc REST parsing.
