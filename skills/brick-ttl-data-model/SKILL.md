---
name: brick-ttl-data-model
description: "Syncs model.json with generated BRICK TTL and exposes SPARQL testing endpoints. Use when operators need semantic data models beyond flat column maps."
---

# BRICK TTL data model

## Prerequisites

`OFDD_MODEL_TTL_PATH`, `OFDD_TTL_SYNC_INTERVAL_SECONDS`. Equipment types from `equipment_type` **or** `brick_type`.

## Quick start

- Import/export `model.json` via bridge model routes.
- Background TTL sync from model changes (`ttl_service.sync()`).
- SPARQL: `POST /api/model/sparql`, predefined queries `GET /api/model/sparql/predefined`.
- FDD composed presets: `GET /api/model/fdd-query-presets/{id}` (no SPARQL — reads model.json + rules).

## Brick class mapping (agents)

Short commissioning types map to Brick schema classes in `ttl_service._brick_equipment_class`:

| model.json | Brick class |
|------------|-------------|
| `brick_type: AHU` | `Air_Handling_Unit` |
| `brick_type: VAV` | `Variable_Air_Volume_Box` |

If SPARQL **AHUs** / **VAV boxes** return 0 but equipment exists, check:

1. Equipment rows have `brick_type` or `equipment_type` set
2. TTL was synced after last model edit
3. Classify with `workspace/api/openfdd_bridge/equipment_classify.py`

## Verification

`POST /api/model/validate`; predefined SPARQL `GET /api/model/sparql/predefined`; FDD preset `ahus_vavs_zones` should match manual AHU/VAV counts.

## Reference

`docs/rcx-central/model-queries.md`, Edge React `DataModelSparqlPanel.tsx`.
