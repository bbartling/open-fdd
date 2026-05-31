---
name: local-dev-orchestration
description: "Build and test Open-FDD locally before any Ansible edge deploy. Starts production React + bridge; optional Caddy on :80. Use when deploy=local or before pi_bcn deploy."
---

# Local dev orchestration

## Mandatory gate (before remote deploy)

**Never deploy to `pi_bcn` until local build + tests pass:**

```bash
cd open-fdd
cp workspace/auth.env.example workspace/auth.env.local   # optional, recommended
cp workspace/caddy.env.example workspace/caddy.env.local   # optional; Caddy on :80
./scripts/build_and_test.sh                              # vitest + vite build + pytest
./scripts/run_local.sh start                             # prod UI + stack
```

| Step | Command | Pass criteria |
|------|---------|---------------|
| 1 Build | `./scripts/build_and_test.sh` | vitest + React → `workspace/api/static/app/`, `pytest tests/workspace_bridge` green |
| 2 Run | `./scripts/run_local.sh start` | `curl http://127.0.0.1/health` (Caddy) or `curl http://127.0.0.1:8765/health` |
| 3 Auth | login at dashboard `/login` | operator / integrator / agent from `auth.env.local` |
| 4 Edge | `cd infra/ansible && ./deploy.sh --limit <host>` | only after steps 1–3 |

## One command local stack

```bash
./scripts/run_local.sh restart
```

This **stops**, **rebuilds the production React bundle** (default), and **starts**:

| Process | Port | Notes |
|---------|------|--------|
| **Caddy** (if enabled) | **:80** or **:443** | Public URL — reverse-proxies to bridge |
| Bridge (compiled SPA + API) | **8765** on **127.0.0.1** when Caddy on | Same artifact Ansible rsyncs |
| BACnet commission agent | 8767 | Poll loop runs here |
| Ollama | 11434 | if `ollama.env.local` exists |
| MCP RAG | 8090 | if `mcp.env.local` has `OFDD_MCP_ENABLED=1` |

**Browser URL (Caddy default):** `http://127.0.0.1/` — no port.

Caddy is enabled when `workspace/caddy.env.local` has `OFDD_CADDY_ENABLED=1` (auto-created from `caddy.env.example` on first start). Modes: `http` (proxy only) or `tls` (`:80` redirects to `:443`).

## UI build flags

| Flag | Behavior |
|------|----------|
| *(default)* / `--ui-prod` | `npm run build` → `workspace/api/static/app/` |
| `--ui-test` | `vitest run` then production build (CI-style gate) |
| `--ui-skip` | Skip npm; serve existing bundle (`OFDD_SKIP_UI_BUILD=1` also works) |
| `--dev` | **Also** start Vite on `:5173` — **not** production parity; use for HMR only |

Examples:

```bash
./scripts/run_local.sh restart --ui-test
./scripts/run_local.sh restart --ui-skip
./scripts/run_local.sh start --dev    # optional Vite; dashboard still at Caddy URL when enabled
```

Standalone build scripts:

```bash
./scripts/build_operator_dashboard.sh prod   # default
./scripts/build_operator_dashboard.sh test   # vitest + prod build
```

## Auth roles (firewall / OT LAN)

See [workspace/deploy/SECURITY.md](../../workspace/deploy/SECURITY.md).

- **operator** — local user, read + ingest
- **integrator** — MSI, BACnet write/release + discover
- **agent** — AI automation, Rule Lab + discover (no writes)

Env: `workspace/auth.env.local`, `workspace/caddy.env.local`, `workspace/ollama.env.local`, `workspace/mcp.env.local` (loaded by `run_local.sh`).

## Clean restart

```bash
./scripts/run_local.sh stop
./scripts/run_local.sh restart
```

## Remote deploy

After local pass — ships **compiled** frontend (not Vite dev):

```bash
./scripts/build_and_test.sh
cd infra/ansible
./deploy.sh --limit bacnet_pi -v
```

Do not use for production bench details — see [ansible-linux-bench-deploy](../ansible-linux-bench-deploy/SKILL.md).

See [references/REFERENCE.md](references/REFERENCE.md).
