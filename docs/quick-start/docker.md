---
title: Run with Docker images
parent: Quick Start
nav_order: 1
---

# Run with Docker images

Deploy Open-FDD on a Linux edge host using **three published GHCR images**. No git clone required.

## Images

| GHCR image | Service | Role |
|------------|---------|------|
| `ghcr.io/bbartling/openfdd-bridge` | `bridge` | Operator API, dashboard, historian ingest |
| `ghcr.io/bbartling/openfdd-commission` | `commission` | BACnet discover/read/write **and poll loop** |
| `ghcr.io/bbartling/openfdd-mcp-rag` | `mcp-rag` | Doc-search sidecar |

Compose defaults to **`latest`**. Pin a dated tag with `export OPENFDD_IMAGE_TAG=2026.06.07-edge` when needed.

## 1. Install and validate Docker

```bash
sudo systemctl enable --now docker
sudo usermod -aG docker "$USER"
newgrp docker   # or log out/in

docker --version
docker compose version
docker ps
docker run --rm hello-world
```

Expect: `active` / `enabled` for docker, `docker` in `groups`, hello-world succeeds.

## 2. Bootstrap the site (one script)

Downloads `docker-compose.yml`, creates `workspace/`, generates `auth.env.local`, and sets `BACNET_BIND` from the host LAN NIC (e.g. `ens192` → `10.200.200.185/24:47808`):

```bash
curl -fsSL -o /tmp/openfdd_edge_bootstrap.sh \
  https://github.com/bbartling/open-fdd/raw/refs/heads/master/scripts/openfdd_edge_bootstrap.sh
bash /tmp/openfdd_edge_bootstrap.sh
```

Bootstrap + pull + start in one go:

```bash
bash /tmp/openfdd_edge_bootstrap.sh --start
```

Options:

| Flag | Purpose |
|------|---------|
| `--start` | `docker compose pull && up -d` after layout |
| `--image-tag TAG` | default `latest` (falls back to `2026.06.07-edge`) |
| `--repo-ref BRANCH` | branch for `compose.edge.yml` if not on `master` yet |
| `--force-auth` | regenerate `auth.env.local` |
| `--show-secrets` | print passwords at end (lab only) |

From a repo checkout: `./scripts/openfdd_edge_bootstrap.sh --start`

The script prints **BACnet NIC**, **BACNET_BIND**, and file paths — **validate** `commission.env` before polling OT devices:

```bash
nano ~/open-fdd/workspace/bacnet/commissioning/commission.env
```

## 3. Start stack (if you skipped `--start`)

```bash
cd ~/open-fdd
docker compose pull
docker compose up -d
docker compose ps
curl -sf http://127.0.0.1:8765/health
```

Expected: **bridge**, **commission**, **mcp-rag** — all `Up`.

## Long-term operation

### Survive power cycles

All services use `restart: unless-stopped`. After reboot:

```bash
cd ~/open-fdd && docker compose ps
curl -sf http://127.0.0.1:8765/health
```

### Start / stop / restart

```bash
cd ~/open-fdd
docker compose up -d          # idempotent
docker compose stop
docker compose restart commission
docker compose logs -f --tail 100 commission
```

{: .warning }
> Never run `docker compose down -v` or delete `workspace/` on a live site.

### LAN access

Put **Caddy** (or nginx) on port 80 → `127.0.0.1:8765`, or expose 8765 through the firewall.

## Next steps

→ [First login and health check](health-check)  
→ [Updating the stack](updating) — `./scripts/openfdd_site_update.sh`
