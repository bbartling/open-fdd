# Local UI build and inspection

Run the Rust edge locally, open the dashboard in a browser, and verify auth and main tabs.

**Canonical build recipes:** [local-dev.md](./local-dev.md) (localhost, Caddy remote TLS, auth, troubleshooting).

## Build recipes (quick reference)

| Goal | Command |
|------|---------|
| Local image (8 GB safe) | `./scripts/openfdd_local_up.sh --build` |
| Restart bridge | `./scripts/openfdd_local_up.sh` |
| UI inspection + smoke | `./scripts/openfdd_inspection_build.sh --build --smoke` |
| Remote HTTPS (Caddy) | `./scripts/openfdd_local_caddy_up.sh --mode tls --lan-ip <IP>` |
| GHCR desktop profile | see below |

## Prerequisites

- Docker (Compose v2)
- Git
- Optional: Node 20+ if you change the React dashboard (`workspace/dashboard`)

Auth: `workspace/auth.env.local` holds **bcrypt hashes** (never commit). Login passwords are in **`workspace/bootstrap_credentials.once.txt`** after `./scripts/openfdd_auth_init.sh --show-secrets`.

## Linux — GHCR image (recommended when publish is green)

```bash
git clone https://github.com/bbartling/open-fdd.git
cd open-fdd
cp .env.example .env   # optional overrides
export OPENFDD_COMPOSE_ROOT="$PWD"

docker compose -f docker/compose.edge.rust.yml \
  -f docker/compose.desktop.json-csv.yml \
  --profile desktop-json-csv up -d

curl -fsS http://127.0.0.1:8080/api/health
xdg-open http://127.0.0.1:8080/   # or your browser
```

If `ghcr.io/bbartling/openfdd-edge-rust:latest` is missing, build from source (below) or set `OPENFDD_IMAGE_TAG` to a published SHA tag from GitHub Packages.

## Linux — build image from source (8 GB RAM hosts)

Full root `Dockerfile` release builds can OOM on ~8 GB machines. Prefer limiting parallel Rust jobs:

```bash
export OPENFDD_COMPOSE_ROOT="$PWD"
docker build --build-arg CARGO_BUILD_JOBS=1 -t open-fdd-openfdd-bridge:local .
```

Then point compose at the local tag (override `image:` in a small override file) or run the bridge container directly with `workspace/` mounted.

On branches that include `scripts/openfdd_local_up.sh` and `Dockerfile.local`, use:

```bash
./scripts/openfdd_local_up.sh --build   # first time only (~30–50 min on 8 GB)
./scripts/openfdd_local_up.sh           # subsequent starts (seconds)
curl -fsS http://127.0.0.1:8080/api/health
```

## Windows Docker Desktop

See [windows_docker_desktop.md](./windows_docker_desktop.md). Quick path:

```powershell
git clone https://github.com/bbartling/open-fdd.git
cd open-fdd
Copy-Item .env.example .env
$env:OPENFDD_COMPOSE_ROOT = (Get-Location).Path
docker compose -f docker/compose.edge.rust.yml `
  -f docker/compose.desktop.json-csv.yml `
  --profile desktop-json-csv up -d
curl.exe -fsS http://localhost:8080/api/health
Start-Process http://localhost:8080
```

Remote Caddy TLS on Linux bench: use `./scripts/openfdd_local_caddy_up.sh` — see [local-dev.md](./local-dev.md).

## Login

Default users: `integrator`, `operator`, `agent`.

**Password:** plaintext from `workspace/bootstrap_credentials.once.txt` — **not** the `OFDD_*_PASSWORD_HASH=` lines in `auth.env.local`.

```bash
./scripts/openfdd_auth_init.sh --rotate --all --show-secrets --restart
OPENFDD_BRIDGE_BASE=http://127.0.0.1:8080 ./scripts/openfdd_auth_smoke.sh
```

## Pages to inspect

| Path | Purpose |
| --- | --- |
| `/` | Building status |
| `/login` | Auth |
| `/live-fdd-validation` | Generic validation harness status |
| `/data-management` | Storage summary + purge preview (integrator) |
| `/json-api` | JSON API sources |
| `/bacnet` | Override export (disabled in desktop-json-csv profile) |

Export APIs (authenticated): `/api/export/historian.csv`, `/api/bacnet/overrides/export`, etc. Sidecars: `scripts/openfdd_csv_export_sidecar.sh`.

## JSON/CSV-only mode (no BACnet/Modbus)

Use `docker/compose.desktop.json-csv.yml` with `--profile desktop-json-csv`. Stack health shows field-bus services as **disabled**, not unhealthy:

- `OPENFDD_BACNET_ENABLED=0`
- `OPENFDD_MODBUS_ENABLED=0`
- `OPENFDD_HAYSTACK_ENABLED=0`
- `OPENFDD_JSON_API_ENABLED=1`
- `OPENFDD_IMPORT_ENABLED=1`
- `OPENFDD_EXPORT_ENABLED=1`

## Validate locally (optional)

```bash
./scripts/audit_no_hardcoding.sh
OPENFDD_COMPOSE_ROOT="$PWD" docker compose -f docker/compose.edge.rust.yml config -q
cd workspace/dashboard && npm ci && npm run build
```

Rust tests require `cargo` on the host or run in CI / Docker builder stage.

## Troubleshooting

- **Port 8080 in use:** stop conflicting service or change compose port mapping.
- **GHCR pull fails:** build locally or check [Publish Rust edge to GHCR](https://github.com/bbartling/open-fdd/actions) workflow on `master`.
- **Login fails:** verify `workspace/auth.env.local` is mounted and restart bridge.
- **Build OOM:** use `CARGO_BUILD_JOBS=1`, close other apps, avoid `docker compose up --build` on root compose for full-edge profiles.
