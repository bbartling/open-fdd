---
title: Modular Architecture
nav_order: 4
---

# Modular Architecture

Open-FDD supports incremental modular operation while keeping one-command orchestration via `scripts/bootstrap.sh`.

## Module contracts

| Module | Concern | Current services |
|--------|---------|------------------|
| Collector | BACnet collection and ingestion | `db`, `bacnet-server`, `bacnet-scraper` |
| Model | Brick/data-model CRUD and SPARQL | `db`, `api`, `frontend`, `caddy` |
| Engine | Pandas/YAML FDD execution | `db`, `fdd-loop`, `weather-scraper` |
| Interface | API, websocket, MCP/OpenClaw orchestration | `api`, `frontend`, `caddy`, `mcp-rag` |

## Bootstrap mode matrix

Use:

```bash
./scripts/bootstrap.sh --mode <full|collector|model|engine>
```

- `full` (default): all major services.
- `collector`: BACnet collector only.
- `model`: API/UI/modeling path.
- `engine`: FDD loop path.

Optional overlays still apply (`--with-grafana`, `--with-mcp-rag`, `--with-mqtt-bridge`).

## Feature coverage by mode

| Feature | collector | model | engine | full |
|---------|-----------|-------|--------|------|
| BACnet gateway + scrape | yes | no | no | yes |
| CRUD API + docs | no | yes | no | yes |
| React frontend + Caddy | no | yes | no | yes |
| SPARQL/model workflows | no | yes | no | yes |
| FDD loop (Pandas/YAML) | no | no | yes | yes |
| Weather loop | no | no | yes | yes |
| MCP RAG sidecar | optional overlay | optional overlay | optional overlay | optional overlay |

## Migration stance

The repository remains a single integrated codebase while contracts and modes are formalized. This avoids a hard split now and enables later package/repo extraction with fewer regressions.

