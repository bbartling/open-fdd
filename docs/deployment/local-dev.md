# Local development (memory-safe)

## Why not `docker compose up --build`?

The root `Dockerfile` runs **npm build + release Rust (DataFusion/Arrow)** inside Docker. On an 8 GB host that can exhaust RAM, trigger the Linux OOM killer, and drop SSH — requiring a hard reboot.

Use the **local overlay** instead (`Dockerfile.local` + `docker-compose.local.yml`).

## Build recipes (pick one)

| Goal | Command | URL |
|------|---------|-----|
| **First local image + dashboard** | `./scripts/openfdd_local_up.sh --build` | http://127.0.0.1:8080 |
| **Restart after code/UI change** | `cd workspace/dashboard && npm run build` then `./scripts/openfdd_local_up.sh` | http://127.0.0.1:8080 |
| **UI inspection (auth + tab smoke)** | `./scripts/openfdd_inspection_build.sh --build --smoke` | http://127.0.0.1:8080 |
| **JSON/CSV-only (no BACnet/Modbus)** | `./scripts/openfdd_inspection_build.sh --desktop --smoke` | http://127.0.0.1:8080 |
| **Remote LAN dial-in (Caddy TLS)** | `./scripts/openfdd_remote_up.sh` | https://\<LAN-IP\>/ |
| **Health check (API + auth)** | `./scripts/openfdd_health_check.sh --remote --auth` | — |
| **Pull GHCR image (no bench compile)** | `./scripts/openfdd_bench_pull_ghcr.sh` | — |
| **One-time bench hardening** | `./scripts/openfdd_bench_setup.sh` | cron + buildx + bench.env |
| **Extend root disk (once, sudo)** | `sudo ./scripts/openfdd_bench_extend_disk.sh` | ~233G total |
| **Regenerate TLS cert for new IP** | add `--regen-certs` to Caddy command | https://\<LAN-IP\>/ |
| **GHCR compose (when publish is green)** | see [local_ui_build.md](./local_ui_build.md) | http://127.0.0.1:8080 |

Logs for local bridge starts: `workspace/logs/local-up.log`

## Bench long-term (bensbench / 8 GB / small root)

Rust edge **images are built in GitHub Actions** (`.github/workflows/rust-ghcr.yml` → `ghcr.io/bbartling/openfdd-edge-rust`). The bench should **pull**, not compile, unless you explicitly opt in.

One-time setup:

```bash
./scripts/openfdd_bench_setup.sh              # buildx hint, weekly cron, workspace/bench.env.local
sudo ./scripts/openfdd_bench_extend_disk.sh   # grow / from ~100G to full ~233G disk (once)
```

Daily / remote:

```bash
./scripts/openfdd_remote_up.sh                # cleanup + GHCR pull + Caddy + health (no --build)
./scripts/openfdd_health_check.sh --remote --auth
```

**React UI local dev** (hot reload — no Docker Rust compile):

```bash
./scripts/openfdd_ui_dev.sh                   # Vite http://127.0.0.1:5173 → API on :8080
./scripts/openfdd_ui_dev.sh --lan             # Vite on all interfaces for remote browser
./scripts/openfdd_ui_dev.sh --build-only      # sync frontend/ only (Caddy :443 path)
```

| Policy | Default |
|--------|---------|
| Local Docker `--build` | **Off** (`OPENFDD_ALLOW_LOCAL_BUILD=0` in `workspace/bench.env.local`) |
| `CARGO_BUILD_JOBS` | `1` |
| Weekly Docker cleanup | Cron Sun 03:00 → `openfdd_docker_maintenance.sh --aggressive` |
| GHCR publish | GitHub Actions on `master` / tags — **not on the bench** |

Rare local rebuild (12GB+ free disk required):

```bash
OPENFDD_ALLOW_LOCAL_BUILD=1 ./scripts/openfdd_local_up.sh --build
```

## Auth and login

`workspace/auth.env.local` stores **bcrypt hashes only** — do not paste `OFDD_*_PASSWORD_HASH=` values into the login form.

| File | Purpose |
|------|---------|
| `workspace/auth.env.local` | Hashes + JWT secret (gitignored) |
| `workspace/bootstrap_credentials.once.txt` | **Plaintext passwords** (one-time handoff, gitignored) |

Generate or rotate:

```bash
./scripts/openfdd_auth_init.sh --rotate --all --show-secrets --restart
```

Save printed passwords or `bootstrap_credentials.once.txt`, then delete the handoff file when done.

Verify login (no secrets printed):

```bash
OPENFDD_BRIDGE_BASE=http://127.0.0.1:8080 ./scripts/openfdd_auth_smoke.sh
# Caddy TLS:
OPENFDD_BRIDGE_BASE=https://127.0.0.1 ./scripts/openfdd_auth_smoke.sh   # health via curl -k if needed
```

Default users: `operator` (read-only), `integrator`, `agent`.

## Quick start (localhost only)

```bash
cd ~/open-fdd

# First time only (15–40 min on 8 GB; logs to workspace/logs/local-up.log)
./scripts/openfdd_local_up.sh --build

# Later starts (seconds, no rebuild)
./scripts/openfdd_local_up.sh
```

Open **http://127.0.0.1:8080** and sign in with plaintext from bootstrap (see above).

## Remote dial-in (production-like Caddy + TLS)

After the local image exists (`openfdd_local_up.sh --build`):

```bash
# Example: bench at 192.168.204.55
./scripts/openfdd_local_caddy_up.sh --mode tls --lan-ip 192.168.204.55

# If cert was generated without this IP before:
./scripts/openfdd_local_caddy_up.sh --mode tls --lan-ip 192.168.204.55 --regen-certs
```

What you get:

- Caddy on **0.0.0.0:80** and **:443** (all interfaces)
- Bridge internal only (`127.0.0.1:8080` on host; Caddy reverse-proxies to `openfdd-bridge:8080`)
- Self-signed TLS with LAN IP in cert SANs
- Same JWT users as local/prod

From another machine: **https://192.168.204.55/** (accept browser cert warning).

Optional client hosts entry: `192.168.204.55 openfdd.local` → **https://openfdd.local/**

HTTP-only lab mode:

```bash
./scripts/openfdd_local_caddy_up.sh --mode http --lan-ip 192.168.204.55
```

Firewall on the server:

```bash
sudo ufw allow 443/tcp
sudo ufw allow 80/tcp   # optional; redirects to HTTPS in TLS mode
```

Health check:

```bash
curl -kfsS https://127.0.0.1/api/health
curl -kfsS https://192.168.204.55/api/health
```

More detail: [caddy.md](./caddy.md), [operations/production-caddy.md](../operations/production-caddy.md).

## What the local path does

| Piece | Behavior |
|-------|----------|
| `Dockerfile.local` | Skips npm in Docker; uses repo `frontend/`; `cargo -j 1` |
| `docker-compose.local.yml` | Bridge only, binds `127.0.0.1:8080`, auth read from mounted `workspace/` |
| `docker-compose.local.caddy.yml` | Caddy profile; exposes :80/:443 |
| `openfdd_local_up.sh` | Memory check, build `--memory=3g`, health wait, logging |
| `openfdd_local_caddy_up.sh` | Cert generation, Caddy + bridge compose up |
| `openfdd_inspection_build.sh` | Dashboard build, optional auth/UI smoke, no long validation |

## Environment

| Variable | Default | Purpose |
|----------|---------|---------|
| `OPENFDD_CARGO_BUILD_JOBS` | `1` | Parallel rustc jobs during image build |
| `OPENFDD_BACNET_ENABLED` | `1` in local compose | Set `0` for JSON/CSV-only inspection |
| `OPENFDD_CADDY_MODE` | `tls` | `http` or `tls` for Caddy script |
| `OPENFDD_CADDY_HOSTNAME` | `openfdd.local` | TLS site name / cert CN |

## UI changes

Rebuild dashboard on the **host** (lighter than in-Docker npm):

```bash
cd workspace/dashboard && npm ci && npm run build
./scripts/openfdd_local_up.sh   # restart container, no --build unless Rust changed
```

After **Rust** changes:

```bash
./scripts/openfdd_local_up.sh --build
```

After **Caddy or cert** changes:

```bash
./scripts/openfdd_local_caddy_up.sh --mode tls --lan-ip <IP> --regen-certs
```

## Troubleshooting

```bash
tail -f workspace/logs/local-up.log
docker compose -f docker-compose.local.yml logs -f openfdd-bridge
docker compose -f docker-compose.local.yml -f docker-compose.local.caddy.yml --profile caddy logs -f openfdd-caddy
docker compose -f docker-compose.local.yml down   # never use down -v
```

| Symptom | Fix |
|---------|-----|
| Caddy script: missing image | `./scripts/openfdd_bench_pull_ghcr.sh` or `./scripts/openfdd_remote_up.sh` |
| Disk full / crash during build | `./scripts/openfdd_docker_maintenance.sh --aggressive`; extend disk with `sudo ./scripts/openfdd_bench_extend_disk.sh` |
| Login “invalid credentials” | Use bootstrap plaintext, not bcrypt hash |
| Remote TLS cert warning | Expected (self-signed); use `--regen-certs` if wrong IP |
| Remote timeout | `sudo ufw allow 443/tcp`; check routing to LAN IP |
| Build OOM | `OPENFDD_CARGO_BUILD_JOBS=1`, add swap, use buildx memory cap |

If build still OOMs, install buildx for memory-capped builds:

```bash
sudo apt install docker-buildx-plugin   # Debian/Ubuntu
```

## GHCR compose

Production edge compose pulls `ghcr.io/bbartling/openfdd-edge-rust`. **GitHub Actions** builds and pushes multi-arch images (`rust-ghcr.yml`); the bench pulls `:latest` via `./scripts/openfdd_bench_pull_ghcr.sh`. See [local_ui_build.md](./local_ui_build.md).

## See also

- [local_ui_inspection.md](./local_ui_inspection.md) — click-through UI smoke, no long validation
- [local_ui_build.md](./local_ui_build.md) — GHCR vs local Dockerfile
- [windows_docker_desktop.md](./windows_docker_desktop.md) — Docker Desktop on Windows
- [security/rust-edge-auth.md](../security/rust-edge-auth.md) — auth file format
