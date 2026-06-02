---
title: Operator dashboard (Rule Lab)
parent: How-to guides
nav_order: 6
---

# Operator dashboard (Rule Lab)

The **operator stack** lives under `workspace/`. Python runs on the **bridge host** (pandas, NumPy, sandboxed Rule Lab code); the browser is a compiled React SPA (same artifact Ansible ships to edge hosts).

## Layout

| Path | Role |
|------|------|
| `workspace/api/` | FastAPI bridge (`openfdd_bridge`) — API on **8765** |
| `workspace/api/static/app/` | **Production** React build (served by bridge) |
| `workspace/dashboard/` | React source — build only; not served at runtime on edge |
| `workspace/data/` | Feather store, rules, model JSON |
| `workspace/deploy/` | Caddy + legacy systemd unit examples (non-Docker edges) |
| `bacnet_toolshed/` | BACnet commission agent + poll loop |

## Quick start (recommended — Docker)

```bash
pip install -e ".[dev]"
cp workspace/auth.env.example workspace/auth.env.local    # optional

./scripts/build_and_test.sh          # vitest + prod UI + pytest (first time)
./scripts/docker_build.sh            # once per image change
./scripts/openfdd_stack.sh up        # bridge + commission + mcp-rag on :8765
```

Open **`http://127.0.0.1:8765/`**. On field VMs, Caddy serves **`http://<lan-ip>/`** (see [Edge deploy (Docker)](../edge_deploy_docker.md)).

**BACnet lab (bensserver):** `docker compose -f docker/compose.dev.yml -f docker/compose.bench.yml up -d` and `./scripts/setup_local_testbench.sh`.

### Legacy quick start (systemd on host)

```bash
./scripts/run_local.sh restart       # venv + systemd units + optional Caddy
```

`run_local.sh` rebuilds the production UI each restart unless **`--ui-skip`**.

### UI build modes

| Command | What it does |
|---------|----------------|
| `./scripts/run_local.sh restart` | Production `vite build` (default) |
| `./scripts/run_local.sh restart --ui-test` | `vitest run` + production build |
| `./scripts/run_local.sh restart --ui-skip` | Skip npm; use existing `static/app/` |
| `./scripts/run_local.sh start --dev` | Also Vite on **5173** (HMR only — not edge parity) |

CI / pre-deploy gate:

```bash
./scripts/build_and_test.sh   # vitest + prod build + pytest
```

## Manual dev (two terminals)

For rapid UI iteration without rebuilding:

```bash
# Terminal 1 — API
export OPENFDD_REPO_ROOT="$(pwd)"
export OFDD_DESKTOP_DATA_DIR="$PWD/workspace/data"
cd workspace/api && uvicorn openfdd_bridge.main:app --reload --port 8765

# Terminal 2 — Vite dev (proxies /api to 8765)
cd workspace/dashboard && npm ci && npm run dev
```

Open `http://127.0.0.1:5173`. For **Ansible/production parity**, use `run_local.sh` without `--dev` and hit the Caddy or `:8765` compiled URL.

## Production build only

```bash
./scripts/build_operator_dashboard.sh prod   # or: test (vitest + build)
# Bridge serves workspace/api/static/app/
```

## Tabs (auth may be required)

| Route | Page |
|-------|------|
| `/` | Building check-engine (public) |
| `/faults` | Fault catalog (public) |
| `/rule-lab` | Python Rule Lab |
| `/data-model` | BRICK model + rule mapping |
| `/plot` | Feather trend plots |
| `/bacnet` | BACnet commissioning |
| `/agent` | Local Ollama chat |
| `/host` | CPU/RAM charts + data-disk space |

## Rule Lab modes

1. **Per-row rule** — `evaluate(row, cfg, …)` → `POST /api/playground/test-rule`
2. **DataFrame script** — `out = {"df": …}` → `POST /api/playground/run-script`

Saved rules use a **dual-file** layout under `workspace/data/`:

- **`rules_store.json`** — metadata, config, bindings, `fault_code`, `source_path`
- **`rules_py/*.py`** — canonical Python (always written on save; this is what `fdd_runner` executes)

The Rule Lab editor loads/saves via the bridge API; the footer shows the `.py` path. Bindings (which BACnet points a rule uses) are set on **`/data-model`**, not Rule Lab.

**Full detail:** [Rule Lab — Python storage & shared editing](rule_lab_storage) (browser flow, AI tools, scheduled loop, BACnet → feather pipeline).

Schedule batch runs: `POST /api/rules/batch`, edge `openfdd-fdd-loop.timer` (Docker: exec into bridge), or local `docker compose exec bridge python -m openfdd_bridge.fdd_runner --once`.

## Auth (OT LAN)

Copy `workspace/auth.env.example` → `auth.env.local`. When `OFDD_AUTH_SECRET` is set, protected routes require login.

See `workspace/deploy/README.md`, `workspace/deploy/SECURITY.md`.

## AI maintainers

Skills: **`fastapi-bridge-api`**, **`react-operator-dashboard`**, **`rules-crud-and-batch-run`**.

- Rule storage & shared human/AI editing: [Rule Lab — Python storage](rule_lab_storage)
- Ollama chat: `POST /openfdd-agent/chat`; rule writes: `POST /openfdd-agent/tool` (`rules.save`) with **agent** role

See also [Skills and agent shell](skills_and_agent) and [BACnet toolshed](../bacnet/index).
