---
title: Data flow
parent: Architecture
nav_order: 2
---

# Data flow

## Telemetry ingest

1. **Commission poll loop** (inside the `commission` container) reads enabled BACnet points from `points.csv` on a schedule (host network, BACnet `:47808`).
2. RPM results append to `workspace/bacnet/polls/samples.csv` (long format).
3. **Bridge ingest worker** watches `samples.csv` and loads new rows into the **feather store** (`workspace/data/feather_store/`).
4. Point registry (`points.csv`, discovered inventory) ties BACnet objects to `series_id`.

```
BACnet devices → commission (poll loop) → samples.csv → bridge (ingest) → feather_store
```

Details: [BACnet polling](../bacnet/polling), [Containers](containers).

## Rule evaluation

1. Rules are Python files in `workspace/data/rules_py/` with metadata in `rules_store.json`.
2. **Bindings** map rules to points via the Brick model (`fdd_input` tags).
3. Batch runner (`POST /api/rules/batch` or host timer) produces `fdd_results.json`.
4. Dashboard **faults** view and check-engine status read aggregated results.

## Model sync

- Commissioning imports update `model.json` / TTL graph.
- `POST /api/model/sync-ttl` refreshes SPARQL-backed tree used by the UI.

## Retention

Feather files grow on disk; retention is configurable (`workspace/data.env.local`). Image upgrades must **preserve** `workspace/data/` — backup before `docker compose up -d --force-recreate`. See [Updating the stack](../quick-start/updating).
