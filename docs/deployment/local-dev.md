# Local development (memory-safe)

## Why not `docker compose up --build`?

The root `Dockerfile` runs **npm build + release Rust (DataFusion/Arrow)** inside Docker. On an 8 GB host that can exhaust RAM, trigger the Linux OOM killer, and drop SSH — requiring a hard reboot.

Use the **local overlay** instead.

## Quick start (recommended)

```bash
cd ~/open-fdd

# First time only (15–40 min on 8 GB; logs to workspace/logs/local-up.log)
./scripts/openfdd_local_up.sh --build

# Later starts (seconds, no rebuild)
./scripts/openfdd_local_up.sh
```

Open **http://127.0.0.1:8080** and log in with `workspace/auth.env.local` credentials.

## What the local path does

| Piece | Behavior |
|-------|----------|
| `Dockerfile.local` | Skips npm in Docker; uses repo `frontend/`; `cargo -j 1` |
| `docker-compose.local.yml` | Bridge only, binds `127.0.0.1:8080`, desktop protocol flags |
| `openfdd_local_up.sh` | Memory check, build `--memory=3g`, health wait, logging |

## Environment

| Variable | Default | Purpose |
|----------|---------|---------|
| `OPENFDD_CARGO_BUILD_JOBS` | `1` | Parallel rustc jobs during image build |
| `OPENFDD_BACNET_ENABLED` | `0` | Desktop mode |

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

## Troubleshooting

```bash
tail -f workspace/logs/local-up.log
docker compose -f docker-compose.local.yml logs -f openfdd-bridge
docker compose -f docker-compose.local.yml down   # never use down -v
```

If build still OOMs: add swap, set `OPENFDD_CARGO_BUILD_JOBS=1`, close browsers/IDE, or install buildx for memory-capped builds:

```bash
sudo apt install docker-buildx-plugin   # Debian/Ubuntu
```

## GHCR / Caddy

Production edge compose pulls `ghcr.io/bbartling/openfdd-edge-rust` — use `./scripts/openfdd_local_up.sh` until a GHCR tag is published or you build and tag locally.

## Remote dial-in (production-like Caddy + TLS)

After the local image is built:

```bash
# Wait for ./scripts/openfdd_local_up.sh --build to finish, then:
./scripts/openfdd_local_caddy_up.sh --mode tls
```

- Caddy listens on **0.0.0.0:443** (and redirects :80 → HTTPS)
- Bridge stays internal; **same `workspace/auth.env.local`** JWT users
- Open from another machine: `https://<your-LAN-IP>/` (accept self-signed cert warning)
- Optional hosts entry on client: `<LAN-IP> openfdd.local`

HTTP-only lab mode:

```bash
./scripts/openfdd_local_caddy_up.sh --mode http
```

Firewall on the server if needed:

```bash
sudo ufw allow 443/tcp
sudo ufw allow 80/tcp
```
