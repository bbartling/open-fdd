---
title: Overview
parent: Data modeling
nav_order: 1
---

# Data model flow

Open-FDD uses a **Brick-semantic data model** (knowledge graph) for sites, equipment, and points. BACnet discovery RDF (from bacpypes3 in diy-bacnet-server) is merged into the same graph. CRUD and discovery both update the model; **all backend queries are SPARQL-driven** (rdflib Graph parse + SPARQL; no grep or text search on the TTL). Rules resolve inputs via `ofdd:mapsToRuleInput` in TTL.

---

## Flow

```
Sites + Equipment + Points (DB)  ← single source of truth
         │
         ▼
  Data-model export / CRUD
         │
         ▼
  Brick TTL (config/brick_model.ttl)  ← reserialized on every create/update/delete (watch the file on disk to see changes)
         │
         ▼
  FDD column_map (external_id → rule_input)
         │
         ▼
  RuleRunner
```

**CRUD and Brick TTL sync:** The database is the single source of truth. Every **create**, **update**, or **delete** on **sites**, **equipment**, or **points** (via API or data-model import) triggers a reserialize: the Brick TTL file (`config/brick_model.ttl`, or `OFDD_BRICK_TTL_PATH`) is regenerated from the current DB and written to disk. So the Brick model is always in sync with CRUD. Deleting a site, device (equipment), or point also cascades to dependent data (timeseries, fault results, etc.) as in a typical CRUD app; see [Danger zone — CRUD deletes](howto/danger_zone#crud-deletes--cascade-behavior).

---

## TTL structure

```turtle
:oat_sensor a brick:Outside_Air_Temperature_Sensor ;
    rdfs:label "OAT (°F)" ;
    brick:isPointOf :ahu_7 ;
    ofdd:mapsToRuleInput "oat" .
```

- Brick classes define sensor types
- `ofdd:mapsToRuleInput` maps to FDD DataFrame columns
- `rdfs:label` for display

---

## Data-model API

| Endpoint | Description |
|----------|-------------|
| `GET /data-model/export` | Export sites, equipment, points as JSON |
| `POST /data-model/import` | Import JSON (creates/updates) |
| `GET /data-model/ttl` | Generate Brick TTL from DB |
| `POST /data-model/sparql` | Run SPARQL query against TTL |

---

## Validation

Use SPARQL to validate:

- All rule inputs have `ofdd:mapsToRuleInput`
- Equipment types and points are consistent
- Brick schema compliance (optional)
