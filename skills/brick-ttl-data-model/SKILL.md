---
name: brick-ttl-data-model
description: "Syncs model.json with generated BRICK TTL and exposes SPARQL testing endpoints. Use when operators need semantic data models beyond flat column maps."
---

# BRICK TTL data model

## Prerequisites

Optional `rdflib` in generated stack; `OFDD_MODEL_TTL_PATH`, `OFDD_TTL_SYNC_INTERVAL_SECONDS`.

## Quick start

- Import/export `model.json` via bridge model routes.
- Background TTL sync from model changes.
- SPARQL: `POST /data-model/sparql`, testing queries under `/data-model/testing/*`.

## Verification

`POST /model/validate`; predefined testing queries `GET /data-model/testing/predefined`.

## Reference

Legacy desktop model/TTL services and DataModel pages.
