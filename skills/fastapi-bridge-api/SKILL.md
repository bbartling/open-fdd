---
name: fastapi-bridge-api
description: "Builds a FastAPI HTTP bridge for Open-FDD sites, ingest, rules, plots, and assistant endpoints. Use when the manifest targets api or when operators need a local REST surface on port 8765."
---

# FastAPI bridge API

## When to use / When not to use

Use when the operator needs HTTP access to sites, ingest, rules, timeseries, or plots.

Skip for pure in-process pandas rule runs ([engine-pandas-fdd](../engine-pandas-fdd/SKILL.md)).

## Prerequisites

- Python 3.10+, FastAPI, uvicorn, pyarrow (if feather storage).
- Generate under `workspace/` per [AGENTS.md](../../AGENTS.md).
- Default bind: `127.0.0.1:8765`.

## Quick start

1. Scaffold `workspace/api/main.py` with FastAPI app and `/health`.
2. Add route groups incrementally: `sites`, `ingest`, `rules`, `timeseries`, `plots` (see reference route table).
3. Wire services to [feather-local-storage](../feather-local-storage/SKILL.md) and `open_fdd.engine` for `/rules/run`.
4. Run: `uvicorn main:app --host 127.0.0.1 --port 8765`.

## Core concepts

- **Bridge** = single FastAPI app; UI and MCP call it over HTTP.
- **CORS:** enable private-LAN only when operator sets `OFDD_CORS_ALLOW_PRIVATE_LAN`.
- **OpenAPI:** expose `/docs` and `/openapi.json` for agent discovery.

## Common patterns

- Mirror legacy tag groups: `health`, `sites`, `ingest`, `rules`, `timeseries`, `plots`, `config`, `assistant`, `sparql`.
- Delegate ingest to driver modules ([driver-csv-ingest](../driver-csv-ingest/SKILL.md), etc.).
- `POST /rules/run` loads feather frames, runs `RuleRunner`, returns flags or frames.

## Compose with other skills

- [feather-local-storage](../feather-local-storage/SKILL.md), [rules-crud-and-batch-run](../rules-crud-and-batch-run/SKILL.md), [codex-agent-on-bridge](../codex-agent-on-bridge/SKILL.md)

## Verification

```bash
curl -s http://127.0.0.1:8765/health
curl -s http://127.0.0.1:8765/openapi.json | head
```

## Gotchas

- Do not copy the monolithic `open_fdd/gateway/server.py` wholesale; implement only manifest-selected routes.
- Long-running ingest belongs in background tasks or explicit job endpoints.

See [references/REFERENCE.md](references/REFERENCE.md) for legacy route inventory.
