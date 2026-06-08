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
2. Map equipment classes (AHU, VAV, …) in the model UI — set `brick_type` on points and `feeds` on equipment (AHU→VAV).
3. Tag points with `fdd_input` roles (zone temp, SAT, damper cmd, …).
4. Bind Rule Lab rules to points, equipment, or BRICK classes (`bindings` in `rules_store.json`).
5. Run `POST /api/model/sync-ttl` after bulk imports.
6. Validate on **Trend plot** with FDD overlays (`?fdd=1`) — faults render on a right-hand 0/1 axis per device scope.

AI Agent and commissioning JSON import can bulk-apply steps 2–4; integrator should review model health before production FDD. See [FDD and assignments](fdd-assignments) and [Ollama and analytics](ollama-analytics).

Export: `GET /api/model/export` (TTL/JSON). Commissioning bundle: `GET /api/model/commissioning-export`. API detail in [Appendix](../appendix/bridge_api).
