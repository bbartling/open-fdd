---
title: Data flow
parent: Architecture
nav_order: 2
---

# Data flow

## Telemetry ingest

1. **Poll driver** reads BACnet points on a schedule (host-network container).
2. Samples land in the **feather store** (`workspace/data/feather_store/`).
3. Point registry (`points.csv`, discovered inventory) ties BACnet objects to `series_id`.

## Rule evaluation

1. Rules are Python files in `workspace/data/rules_py/` with metadata in `rules_store.json`.
2. **Bindings** map rules to points via the Brick model (`fdd_input` tags).
3. Batch runner (`POST /api/rules/batch` or host timer) produces `fdd_results.json`.
4. Dashboard **faults** view and check-engine status read aggregated results.

## Model sync

- Commissioning imports update `model.json` / TTL graph.
- `POST /api/model/sync-ttl` refreshes SPARQL-backed tree used by the UI.

## Retention

Feather files grow on disk; retention policies are configurable on the edge. Image upgrades should **not** delete `workspace/data/` when using `upgrade_edge_ghcr.sh`.
