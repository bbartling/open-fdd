# Windows Docker Desktop — UI inspection

Run Open-FDD on Windows without BACnet/Modbus hardware. JSON API, CSV import/export, and dashboard tabs are enough for UI inspection.

## Prerequisites

- [Docker Desktop](https://www.docker.com/products/docker-desktop/) (WSL2 backend recommended)
- Git

## Quick start (PowerShell)

```powershell
git clone https://github.com/bbartling/open-fdd.git
cd open-fdd
git checkout integration/ui-inspection-build

Copy-Item .env.example .env -ErrorAction SilentlyContinue
$env:OPENFDD_COMPOSE_ROOT = (Get-Location).Path

# Generate auth (first time) — save printed passwords
docker run --rm -v "${PWD}/workspace:/app/workspace" ghcr.io/bbartling/openfdd-edge-rust:latest `
  openfdd-edge auth init --path /app/workspace/auth.env.local --show-secrets

docker compose -f docker/compose.edge.rust.yml `
  -f docker/compose.desktop.json-csv.yml `
  --profile desktop-json-csv up -d

curl.exe -fsS http://127.0.0.1:8080/health
Start-Process http://127.0.0.1:8080
```

## Login

- Open http://127.0.0.1:8080/login
- User: `integrator` (or `operator` / `agent`)
- Password: from bootstrap output or `workspace/bootstrap_credentials.once.txt`
- **Do not** use values from `OFDD_*_PASSWORD_HASH=` in `auth.env.local`

## Build dashboard from source (optional)

If the bundled frontend is stale:

```powershell
cd workspace/dashboard
npm ci
npm run build
cd ../..
docker compose -f docker/compose.edge.rust.yml `
  -f docker/compose.desktop.json-csv.yml `
  --profile desktop-json-csv up -d --force-recreate
```

## Caddy / HTTPS (optional)

If using the `caddy-tls` profile from `docker/compose.edge.rust.yml`:

```powershell
curl.exe -k -fsS https://localhost/health
Start-Process https://localhost
```

## Troubleshooting

| Issue | Fix |
| --- | --- |
| Pull fails from GHCR | Log in to `ghcr.io` or build locally on Linux and export image |
| Login invalid | Rotate auth; use plaintext bootstrap file, not bcrypt hash |
| Port 8080 in use | Change compose port mapping or stop conflicting service |
| BACnet/Modbus red | Expected off in `desktop-json-csv` profile — use JSON API tab instead |
| Remote HTTPS from LAN | Linux bench: `./scripts/openfdd_local_caddy_up.sh --mode tls --lan-ip <IP>` — [local-dev.md](./local-dev.md) |

## See also

- [local-dev.md](./local-dev.md) — build recipes including Caddy remote TLS
- [local_ui_inspection.md](./local_ui_inspection.md)

## Intentionally not required

- 1-hour / 6-hour validation smoke
- Live field hardware
- CSV append/delete long tests

See [local_ui_inspection.md](./local_ui_inspection.md).
