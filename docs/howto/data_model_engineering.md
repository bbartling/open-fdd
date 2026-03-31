---
title: Data model engineering (Brick + 223P MVP)
parent: How-to Guides
nav_order: 14
---

# Data Model Engineering (MVP)

Open-FDD keeps **Brick** as the operational model and adds an **Engineering** layer: schedule-style metadata and **223-style topology** in the database, emitted into the same **knowledge graph** (TTL) you already query for FDD and BACnet.

## What this adds

- Frontend page: **Data Model Engineering**
- Equipment engineering metadata persisted in **`equipment.metadata.engineering`** (PostgreSQL JSON)
- Round-trip via **`PUT /data-model/import`** and **`GET /data-model/export`**
- RDF emission on the unified model (same TTL build as Brick points—see **`open_fdd/platform/data_model_ttl.py`**, **`_append_equipment_engineering`**):
  - **`ofdd:*`** extension predicates for practical fields (design CFM, cooling tons, heating MBH, electrical, feeder panel, source documents, etc.)
  - **`s223:*`** topology patterns for connection points and conduits (inlet/outlet, duct segments, mediums)
- **Data Model Testing** — SPARQL presets and copy-paste examples for engineering + topology

## 223P and what Open-FDD implements

**ASHRAE Standard 223** defines a semantic way to describe how building equipment and media connect. In practice, **“223P”** often means tooling and workflows that capture that connectivity and related engineering data alongside operations.

Open-FDD’s MVP is intentionally narrow:

- It **stores** structured engineering and topology in the DB and **emits** them into RDF using **`s223:`**-namespaced types (e.g. connection points, ducts) plus **`ofdd:`** for non-223 schedule fields.
- Connection endpoint linkage is currently represented with **`ofdd:connectsFromRef`** / **`ofdd:connectsToRef`** string references (MVP), not full RDF object links via `s223:connectsFrom` / `s223:connectsTo`.
- It does **not** claim full Standard 223 validation, certification, or a complete 223 product data model. The value here is **one graph**: Brick + BACnet + timeseries refs + engineering + topology, all queryable with **SPARQL** and aligned with how integrators already think about **connections** and **submittal data**.

## How this connects to FDD, PostgreSQL, and the knowledge graph

The platform already treats the **database as source of truth** and **regenerates** the Brick TTL on CRUD and data-model import. Engineering metadata follows the same pattern.

| Layer | Role |
|--------|------|
| **PostgreSQL** | Sites, equipment (including `metadata.engineering`), points, **`timeseries_readings`**, fault definitions and fault **results** (per run / equipment / time). |
| **TTL (`config/data_model.ttl` or export)** | **Unified RDF**: Brick entities, `ref:BACnetReference` / `ref:TimeseriesReference`, `ofdd:mapsToRuleInput`, BACnet device graph, plus **`ofdd:`** and **`s223:`** from engineering import. |
| **FDD loop** | SPARQL over that graph builds the **column map** (timeseries `external_id` → rule input). Rules are still **pandas over pivoted telemetry**; they do not automatically pull engineering scalars into the DataFrame unless you extend the runner or join externally. |
| **SPARQL / integrations** | Query **design cooling tons** on an AHU, **`brick:feeds`** downstream VAVs, and **BACnet-backed** valve points in **one** graph—then join to SQL on site/equipment/point keys or time windows. |

So: **yes**, the **data model, knowledge graph, and DB** are wired so you can **reason across** “what the equipment is rated for” (engineering), “what it is doing” (time series), and “what the rules said” (faults). That is the foundation for **optimization playbooks**, **GL36-style context**, and **energy impact sketches**.

## Energy penalty and impact calculations (scope)

**Today, core Open-FDD focuses on detection and diagnostics** (fault flags, trends, Grafana/React views). It does **not** ship a calibrated **M&V** or automatic **utility-dollar** engine in the main loop.

**Architecturally, energy penalty workflows are supported** because you can:

1. **SPARQL** equipment for **`ofdd:coolingCapacityTons`**, **`ofdd:heatingCapacityMBH`**, **`ofdd:designCFM`**, and topology (**`brick:feeds`** / **`brick:isFedBy`**).
2. **Resolve points** on that equipment via **`brick:isPointOf`** and **`ref:TimeseriesReference`** → `external_id` / DB table.
3. **Correlate** with fault episodes from the **fault results** tables (or exported CSV) over a time window.
4. Apply a **simple model** (e.g. design capacity × estimated duty fraction × hours × crude kW/ton)—see §5 in `examples/223P_engineering/README.md`.

That path is appropriate for **notebooks**, **downstream analytics services**, or future product features—not a promise that the FDD binary computes kWh for every fault out of the box.

## Backward compatibility

- Existing Brick / BACnet / time-series / `rule_input` workflows are unchanged
- Unknown metadata keys under `engineering` are preserved on import
- Import/export shape remains backward compatible; engineering fields are **optional**

## JSON pattern

Use `equipment[].engineering` in import payloads. Example: `examples/223P_engineering/engineering_import_example.json`.

## RDF pattern

Examples (offline or diff against live export):

- `examples/223P_engineering/engineering_topology_example.ttl` — `s223` connection points + `ofdd` engineering
- `examples/223P_engineering/engineering_graph_mini.ttl` — adds **`brick:feeds`** / **`brick:isFedBy`**, plus a point with **`ref:BACnetReference`** + **`ref:TimeseriesReference`**

## Query examples

- `examples/223P_engineering/README.md` — §4 SPARQL (copy-paste)
- Broader SPARQL patterns: [SPARQL cookbook](../modeling/sparql_cookbook), [External representations](../modeling/external_representations)

## Related docs

- [Data model flow (DB → TTL → FDD)](../modeling/overview)
- [Fault rules overview](../rules/overview) — Brick-driven column map; engineering is complementary metadata for analytics
