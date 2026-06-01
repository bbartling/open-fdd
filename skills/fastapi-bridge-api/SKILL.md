---
name: fastapi-bridge-api
description: "Builds a FastAPI HTTP bridge for Open-FDD sites, ingest, Python rules, plots, and assistant endpoints. Use when the manifest targets api or when operators need a local REST surface on port 8765."
---

# FastAPI bridge API

## Starter codebase (maintain here)

The repo ships a working bridge under **`workspace/api/openfdd_bridge/`**. Extend it — do not restart from scratch unless asked.

| Module | Purpose |
|--------|---------|
| `main.py` | App factory, CORS, static SPA mount |
| `auth.py` | `OFDD_AUTH_SECRET` / `OFDD_WEB_USER` / `OFDD_WEB_PASSWORD` Bearer tokens |
| `playground.py` | Server-side Python sandbox (lint, `evaluate()`, DataFrame scripts) |
| `routes/playground_routes.py` | `/api/playground/*` |
| `routes/rules_routes.py` | `/api/rules/saved`, `/api/rules/batch` — Python Rule Lab persistence |
| `fdd_runner.py` | Scheduled batch runner over saved rules |
| `routes/bacnet_routes.py` | `/config/bacnet`, `POST /ingest/bacnet` |
| `routes/agent_routes.py` | `/openfdd-agent/context`, `/openfdd-agent/chat` |

Run:

```bash
export OPENFDD_REPO_ROOT="$(pwd)"
export OFDD_DESKTOP_DATA_DIR="$PWD/workspace/data"
cd workspace/api && uvicorn openfdd_bridge.main:app --reload --port 8765
```

## When to use / When not to use

Use when the operator needs HTTP access to sites, ingest, Python rules, timeseries, or plots.

Skip for pure in-process library runs ([engine-pandas-fdd](../engine-pandas-fdd/SKILL.md) YAML `RuleRunner` in notebooks).

## Prerequisites

- Python 3.10+, `pip install -r workspace/api/requirements.txt`, `pip install -e .` (pandas; `column_map_from_model` is in the base wheel).
- Default bind: `127.0.0.1:8765` (OT LAN — use reverse proxy + auth, not public internet).

## Playground API (Rule Lab)

| Endpoint | Body | Result |
|----------|------|--------|
| `POST /api/playground/lint` | `{ "code" }` | AST issues |
| `POST /api/playground/test-rule` | `{ "code", "config", "site_id?", "limit?" }` | Per-row sweep events |
| `POST /api/playground/run-script` | `{ "code", "config?", "limit?" }` | DataFrame `out` preview |
| `GET /api/playground/sample-frame` | query `site_id`, `limit` | Demo CSV rows |

Allowed imports in sandbox: `datetime`, `math`, `numpy`, `pandas`, `open_fdd`.

## Saved rules API

| Endpoint | Role |
|----------|------|
| `POST /api/rules/save` | Persist rule after Rule Lab validation |
| `POST /api/rules/batch` | Run all enabled rules → building check-engine |
| `GET /api/rules/saved/{id}/source` | Load `.py` for editor |

## Core concepts

- **Bridge** = single FastAPI app; UI and MCP call it over HTTP.
- **Python rules** = author in browser, execute on bridge (never in-browser).
- **CORS:** dev origins `5173`; set `OFDD_CORS_ALLOW_PRIVATE_LAN=1` only with operator consent.
- **Auth:** when `OFDD_AUTH_*` set, all `/api/*` and `/openfdd-agent/*` require `Authorization: Bearer`.
- **OpenAPI:** `/docs` for agent discovery.

## Compose with other skills

- [feather-local-storage](../feather-local-storage/SKILL.md), [react-operator-dashboard](../react-operator-dashboard/SKILL.md), [rules-crud-and-batch-run](../rules-crud-and-batch-run/SKILL.md), [driver-bacnet-ingest](../driver-bacnet-ingest/SKILL.md), [codex-agent-on-bridge](../codex-agent-on-bridge/SKILL.md)

## Verification

```bash
curl -s http://127.0.0.1:8765/health
curl -s -X POST http://127.0.0.1:8765/api/playground/lint -H 'Content-Type: application/json' -d '{"code":"def evaluate(row, cfg, prev_row=None, rows=None):\n return False\n"}'
pytest tests/workspace_bridge -q
```

## Gotchas

- Do not copy the retired monolithic `open_fdd/gateway/server.py` wholesale; extend `workspace/api`.
- Python never runs in the browser — only on the bridge host.
- Production: build dashboard into `workspace/api/static/app` before serving SPA from uvicorn.
- Legacy YAML `POST /api/rules/run` was removed; use playground + saved Python rules.

See [references/REFERENCE.md](references/REFERENCE.md) and [docs/howto/operator_dashboard.md](../../docs/howto/operator_dashboard.md).
