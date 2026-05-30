# Operator stack deployment (Linux)

## Components

| Piece | Path | Port |
|-------|------|------|
| FastAPI bridge + **production** static UI | `workspace/api/static/app` | 8765 (via Caddy :80 when enabled) |
| React source (build only — not served in prod) | `workspace/dashboard` | — |
| Data / rules | `workspace/data` | — |
| BACnet edge CLIs | `bacnet_toolshed/` | commission 8767 |

## Quick local (production UI — same as Ansible edge)

Build happens on your dev machine; the bridge serves `workspace/api/static/app/` (no Vite, no npm on the host at runtime).

```bash
./scripts/run_local.sh restart
# Dashboard: http://127.0.0.1/  (Caddy) or http://127.0.0.1:8765/  (bridge direct)
# API:       http://127.0.0.1:8765/health
```

Skip rebuild when the UI is unchanged:

```bash
OFDD_SKIP_UI_BUILD=1 ./scripts/run_local.sh restart
```

Optional Vite HMR (not production parity):

```bash
./scripts/run_local.sh start --dev   # also :5173 — use only for rapid UI iteration
```

## Ansible deploy

1. `./scripts/build_and_test.sh` — build React into `workspace/api/static/app`
2. `cd infra/ansible && ./deploy.sh` — rsync static files; **no npm on remote**

## Production (systemd)

1. Build dashboard: `scripts/build_operator_dashboard.sh`
2. Copy `workspace/deploy/systemd/openfdd-bridge.service.example` → `/etc/systemd/system/openfdd-bridge.service`
3. Set `OFDD_AUTH_*` env vars (required for OT LAN)
4. `systemctl enable --now openfdd-bridge`
5. Terminate TLS at Caddy/nginx; do not expose port 8765 to the public internet

## Auth

Set on the bridge host:

- `OFDD_AUTH_SECRET` — long random string
- `OFDD_WEB_USER` / `OFDD_WEB_PASSWORD` — operator login

When unset, auth is disabled (development only).
