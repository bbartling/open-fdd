---
title: Operator dashboard (Rule Lab)
parent: How-to guides
nav_order: 6
---

# Operator dashboard (Rule Lab)

The **operator stack** lives under `workspace/` (committed starter). It mirrors the Bake-a-Py pattern from edge cloud dashboards: **Python is edited in the browser and executed on the bridge host** (pandas + `open_fdd.engine`), not in the browser.

## Layout

| Path | Role |
|------|------|
| `workspace/api/` | FastAPI bridge (`openfdd_bridge`) — port **8765** |
| `workspace/dashboard/` | Vite + React 19 UI — dev port **5173** |
| `workspace/data/` | Sample CSV, YAML rules, feather store |
| `workspace/deploy/` | systemd unit examples |
| `bacnet_toolshed/` | Edge BACnet CLIs → poll CSV → `/ingest/bacnet` |

## Development

```bash
pip install -e ".[dev]"
pip install -r workspace/api/requirements.txt
export OPENFDD_REPO_ROOT="$(pwd)"
export OFDD_DESKTOP_DATA_DIR="$PWD/workspace/data"

# Terminal 1 — API
cd workspace/api && uvicorn openfdd_bridge.main:app --reload --port 8765

# Terminal 2 — UI (proxies /api to 8765)
cd workspace/dashboard && npm ci && npm run dev
```

Open `http://127.0.0.1:5173` → **Rule Lab** → edit Python → **Test on server**.

Production build (serves UI from bridge):

```bash
scripts/build_operator_dashboard.sh   # or .ps1 on Windows
cd workspace/api && uvicorn openfdd_bridge.main:app --host 127.0.0.1 --port 8765
# http://127.0.0.1:8765/
```

## Rule Lab modes

1. **Per-row rule** — define `evaluate(row, cfg, …)`; bridge sweeps the demo frame (`POST /api/playground/test-rule`).
2. **DataFrame script** — full `df` with `open_fdd.engine.RuleRunner`; set `out = {"df": …}` (`POST /api/playground/run-script`).
3. **YAML FDD** — `workspace/data/rules/*.yaml` via `POST /api/rules/run` (integer `0`/`1` flag columns).

## Auth (OT LAN)

Set on the bridge host before production:

```bash
export OFDD_AUTH_SECRET="$(openssl rand -hex 32)"
export OFDD_WEB_USER=operator
export OFDD_WEB_PASSWORD='…'
```

When unset, auth is **off** (local dev only). See `workspace/deploy/README.md` and `workspace/deploy/systemd/`.

## AI maintainers

Agents use skills **`fastapi-bridge-api`** and **`react-operator-dashboard`** to extend routes and pages. Codex CLI, Cursor, Claude Code, or OpenClaw run against the same repo; optional HTTP chat is `POST /openfdd-agent/chat` when `codex` is on PATH.

See also [Skills and agent shell](skills_and_agent) and [BACnet toolshed](../bacnet/index).
