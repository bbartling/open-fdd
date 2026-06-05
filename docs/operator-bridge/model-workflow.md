---
title: Model workflow
parent: Operator Bridge
nav_order: 4
---

# Model workflow

## Brick model

- **Equipment tree** — SPARQL over synced TTL (`workspace/data/data_model.ttl`)
- **Point registry** — BACnet inventory → `series_id` for historian bindings
- **Health score** — orphan points, missing `fdd_input`, stale telemetry

## Typical integrator flow

1. Import or sync BACnet point registry.
2. Map equipment classes (AHU, VAV, …) in the model UI.
3. Tag points with `fdd_input` roles (zone temp, SAT, damper cmd, …).
4. Bind Rule Lab rules to those inputs.
5. Run `POST /api/model/sync-ttl` after bulk imports.

Export: `GET /api/model/export` (TTL/JSON). API detail in [Appendix](../appendix/bridge_api).
