# Local orchestration — reference

## Primary script

`./scripts/run_local.sh` — local edge-like stack:

1. **Production React build** (unless `--ui-skip`) → `workspace/api/static/app/`
2. **Bridge** — uvicorn `openfdd_bridge.main:app` on `OFDD_BRIDGE_PORT` (8765)
3. **Caddy** (when `OFDD_CADDY_ENABLED=1`) — LAN entry `:80` / `:443` → `reverse_proxy 127.0.0.1:8765`
4. Commission agent, Ollama, MCP RAG as configured

Generated Caddy config: `workspace/.local-run/Caddyfile` (from `write_caddyfile()` in `run_local.sh`).

Templates: `workspace/deploy/caddy/Caddyfile.http`, `Caddyfile.tls`.

## URLs

| Mode | Dashboard URL |
|------|----------------|
| Caddy `http` | `http://127.0.0.1/` or `http://<lan-ip>/` |
| Caddy `tls` | `https://127.0.0.1/` (`:80` → `:443` redirect) |
| Caddy off | `http://127.0.0.1:8765/` |
| Vite `--dev` only | `http://127.0.0.1:5173/` (optional HMR; not Ansible parity) |

Health: `GET /health` via Caddy or bridge.

## Env files (workspace/)

| File | Purpose |
|------|---------|
| `auth.env.local` | `OFDD_AUTH_SECRET`, operator/integrator/agent users |
| `caddy.env.local` | `OFDD_CADDY_ENABLED`, `OFDD_CADDY_MODE` (`http` \| `tls` \| `off`) |
| `ollama.env.local` | Local AI agent tier |
| `mcp.env.local` | MCP RAG sidecar |

## Legacy

- `scripts/start-local.sh`, `scripts/start-local.ps1` — superseded by `run_local.sh`
- Bootstrap fields (legacy gateway): `bridge_base`, `mcp_rest_base`, `ui_public_base`, `OFDD_UI_PUBLIC_BASE`

When Caddy serves the compiled SPA, set **`OFDD_UI_PUBLIC_BASE`** to the Caddy URL (e.g. `http://192.168.1.20/`), not `:5173`.
