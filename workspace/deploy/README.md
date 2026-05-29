# Operator stack deployment (Linux)

## Components

| Piece | Path | Port |
|-------|------|------|
| FastAPI bridge + static UI | `workspace/api` | 8765 |
| Vite dev UI (optional) | `workspace/dashboard` | 5173 |
| Data / rules | `workspace/data` | — |
| BACnet edge CLIs | `bacnet_toolshed/` | commission 8767 |

## Quick dev

```bash
./scripts/run_local.sh
# UI  http://127.0.0.1:5173
# API http://127.0.0.1:8765/health
```

Or manually:
pip install -e ".[dev]"
pip install -r workspace/api/requirements.txt
export OPENFDD_REPO_ROOT="$(pwd)"
export OFDD_DESKTOP_DATA_DIR="$PWD/workspace/data"
cd workspace/api && uvicorn openfdd_bridge.main:app --reload --port 8765
```

Second terminal:

```bash
cd workspace/dashboard && npm ci && npm run dev
```

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
