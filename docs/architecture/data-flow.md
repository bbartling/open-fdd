---
title: Data flow
parent: Architecture
nav_order: 2
---

# Data flow

## Telemetry ingest

Open-FDD supports three commissioning drivers. Each appends long-format samples to workspace CSVs and writes **feather shards** tagged by `source` (`bacnet`, `modbus`, `json_api`).

### BACnet

1. **Commission poll loop** (inside the `commission` container) reads enabled BACnet points from `points.csv` on a schedule (host network, BACnet `:47808`).
2. RPM results append to `workspace/bacnet/polls/samples.csv`.
3. **Bridge ingest worker** loads new rows into `feather_store/bacnet/`.

```
BACnet devices → commission (poll loop) → samples.csv → bridge (ingest) → feather_store/bacnet
```

### Modbus TCP

1. Operator configures registers on the **Modbus** tab (or `read_and_store` API).
2. Poll worker reads holding/input registers via Modbus TCP.
3. Samples append to `workspace/modbus/polls/samples.csv` → `feather_store/modbus/`.

### JSON API (HTTP/HTTPS)

1. Operator configures REST endpoints on the **JSON API** tab — GET/POST, Bearer or Basic auth, `${ENV:VAR}` placeholders from `json_api.env.local`, optional TLS verify off for self-signed OT gateways.
2. Poll worker issues HTTP requests (one GET can fan out to multiple JSON paths, e.g. OpenWeather `web-oat-t` / `web-rh` / `web-weather-desc`).
3. Samples append to `workspace/json_api/polls/samples.csv` → `feather_store/json_api/`.
4. FDD batch **merges** `json_api` columns with BACnet/Modbus on the same site (nearest timestamp, 30 min tolerance) for cross-source rules.

```
OT REST / weather API → bridge JSON API worker → samples.csv → feather_store/json_api
                                                      ↘ merged into FDD frame with bacnet/modbus
```

Showcase: [OpenWeatherMap bundle](../drivers/json-api#openweathermap-showcase-recommended-demo). Details: [Driver framework](../drivers/index), [BACnet polling](../bacnet/polling), [JSON API driver](../drivers/json-api), [Containers](containers).

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
