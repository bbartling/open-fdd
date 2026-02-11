---
title: System Modeling Overview
parent: Modeling
nav_order: 1
---

# System Modeling

Open-FDD uses a Brick-semantic data model for equipment and points. Rules resolve inputs via `ofdd:mapsToRuleInput` in TTL.

---

## Flow

```
Sites + Equipment + Points (DB)
         │
         ▼
  Data-model export
         │
         ▼
  Brick TTL (config/brick_model.ttl)
         │
         ▼
  FDD column_map (external_id → rule_input)
         │
         ▼
  RuleRunner
```

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
