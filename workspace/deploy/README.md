# Operator stack deployment (Linux)

## Components

| Piece | Path | Port / URL |
|-------|------|------------|
| **Caddy** (optional LAN entry) | `workspace/caddy.env.local` | **:80** or **:443** → bridge |
| FastAPI bridge + **production** static UI | `workspace/api/static/app` | **8765** (loopback when Caddy on) |
| React source (build only) | `workspace/dashboard` | — |
| Data / feather store | `workspace/data` | — |
| BACnet commission + poll | `bacnet_toolshed/` | **8767** |

## Quick local (production UI — same as Ansible edge)

```bash
./scripts/run_local.sh restart
# Dashboard: http://127.0.0.1/  (Caddy) or http://127.0.0.1:8765/  (Caddy off)
# API health: http://127.0.0.1:8765/health
```

`start` and `restart` run a **production Vite build** by default (`workspace/api/static/app/`). No npm on the remote host at deploy time.

### UI build flags

| Flag | Behavior |
|------|----------|
| *(default)* / `--ui-prod` | Production `vite build` |
| `--ui-test` | `vitest run` + production build |
| `--ui-skip` | Skip npm (`OFDD_SKIP_UI_BUILD=1` also works) |
| `--dev` | Also run Vite on `:5173` (HMR — not production parity) |

```bash
./scripts/run_local.sh restart --ui-test    # CI-style gate locally
./scripts/run_local.sh restart --ui-skip  # UI unchanged, faster restart
./scripts/run_local.sh start --dev        # optional Vite; use Caddy URL for prod-like UI
```

Standalone:

```bash
./scripts/build_operator_dashboard.sh prod
./scripts/build_operator_dashboard.sh test
```

## Caddy

Copy `workspace/caddy.env.example` → `caddy.env.local`:

- **`OFDD_CADDY_ENABLED=1`**, **`OFDD_CADDY_MODE=http`** — `http://<host>/` proxies to bridge
- **`OFDD_CADDY_MODE=tls`** — `:80` redirects to HTTPS on `:443` (run `./scripts/setup_caddy_certs.sh` first)
- **`OFDD_CADDY_MODE=off`** — hit bridge directly on `:8765`

Local Caddyfile is generated at `workspace/.local-run/Caddyfile`. If `:80` bind fails, `run_local.sh` falls back to **:8080**.

## Ansible deploy

1. `./scripts/build_and_test.sh` — vitest + prod build + `pytest tests/workspace_bridge`
2. `cd infra/ansible && ./deploy.sh` — rsyncs `workspace/api/static/app/`; **no npm on remote**

## Production (systemd)

1. `./scripts/build_operator_dashboard.sh prod`
2. Copy `workspace/deploy/systemd/openfdd-bridge.service.example` → `/etc/systemd/system/`
3. Set `OFDD_AUTH_*` env vars (required for OT LAN)
4. `systemctl enable --now openfdd-bridge`
5. Caddy/nginx on `:80`; do not expose `:8765` to the public internet

## Auth

Set on the bridge host:

- `OFDD_AUTH_SECRET` — long random string
- `OFDD_WEB_USER` / `OFDD_WEB_PASSWORD` — operator login (or role-specific vars in `auth.env.example`)

When unset, auth is disabled (development only).

See `workspace/deploy/SECURITY.md` for roles (operator / integrator / agent).
