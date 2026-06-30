# Open-FDD on Windows Docker Desktop

Run the Rust edge in **JSON/CSV-only desktop mode** without BACnet, Modbus, or host networking.

## Prerequisites

- [Docker Desktop for Windows](https://www.docker.com/products/docker-desktop/)
- PowerShell 5+ or Windows Terminal
- Git

## Quick start

```powershell
git clone https://github.com/bbartling/open-fdd.git
cd open-fdd
Copy-Item .env.example .env
$env:OPENFDD_COMPOSE_ROOT = (Get-Location).Path
docker compose -f docker/compose.edge.rust.yml -f docker/compose.desktop.json-csv.yml --profile desktop-json-csv up -d --build
curl.exe -fsS http://localhost:8080/health
Start-Process http://localhost:8080
```

If you use Caddy/TLS locally:

```powershell
curl.exe -k -fsS https://localhost/api/health
Start-Process https://localhost
```

## Auth

On first boot, create credentials:

```powershell
docker compose -f docker/compose.edge.rust.yml exec openfdd-bridge `
  openfdd_edge --init-auth /var/openfdd/workspace/auth.env.local
```

Or run `bash scripts/openfdd_rust_edge_bootstrap.sh` from WSL/Git Bash. Credentials live in
`workspace/auth.env.local` (never commit this file).

Default users: `integrator`, `agent`, `operator` — passwords are generated at init.

## Desktop JSON/CSV mode

This profile starts **only** `openfdd-bridge` with:

- `OPENFDD_BACNET_ENABLED=0`
- `OPENFDD_MODBUS_ENABLED=0`
- `OPENFDD_HAYSTACK_ENABLED=0`
- `OPENFDD_JSON_API_ENABLED=1`
- `OPENFDD_IMPORT_ENABLED=1`
- `OPENFDD_EXPORT_ENABLED=1`

Stack health shows disabled (not unhealthy) for field-bus services.

## Useful pages

| URL | Purpose |
| --- | --- |
| `/` | Building status |
| `/json-api` | JSON API sources |
| `/plot` | Trend lab |
| `/live-fdd-validation` | Validation harness status |
| `/data-management` | Historian storage + purge |

## CSV import/export sidecars

Sidecars call HTTP APIs only — they never read/write Feather files directly.

```powershell
bash scripts/openfdd_csv_import_sidecar.sh --dry-run
bash scripts/openfdd_csv_export_sidecar.sh --dry-run
```

Use WSL or Git Bash on Windows for shell scripts, or schedule via Task Scheduler calling WSL.

## Full edge mode

BACnet + Modbus + Haystack commission services:

```powershell
docker compose -f docker/compose.edge.rust.yml --profile full-edge up -d
```

## Troubleshooting

- **Port 8080 in use:** change bridge port mapping in compose or stop conflicting service.
- **Login fails:** regenerate `workspace/auth.env.local` and restart bridge.
- **Unhealthy commission in full-edge:** expected on desktop if BACnet bind IP is wrong — use simulated mode or desktop profile.
