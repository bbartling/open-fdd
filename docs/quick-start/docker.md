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

**Auth** — bootstrap writes `~/open-fdd/workspace/auth.env.local` (gitignored). This file holds the API signing secret and one username/password per role. Use it for your first dashboard login:

```bash
cat ~/open-fdd/workspace/auth.env.local
```

| Variable | Role |
|----------|------|
| `OFDD_AUTH_SECRET` | Signs session tokens (do not share) |
| `OFDD_OPERATOR_*` | Read-only operator |
| `OFDD_INTEGRATOR_*` | **Default dashboard login** — commissioning + BACnet |
| `OFDD_AGENT_*` | Agent / automation |

Example shape (passwords are **random on first bootstrap only** — existing file is kept on re-runs):

```
OFDD_AUTH_SECRET=<random>
OFDD_OPERATOR_USER=operator
OFDD_OPERATOR_PASSWORD=<random>
OFDD_INTEGRATOR_USER=integrator
OFDD_INTEGRATOR_PASSWORD=<random>
OFDD_AGENT_USER=agent
OFDD_AGENT_PASSWORD=<random>
```

Sign in as **integrator** with the password from that file → [First login and health check](health-check).

| Action | Touches `auth.env.local`? |
|--------|---------------------------|
| First `bash …bootstrap.sh --start` | Creates file with random passwords (if missing) |
| `bash …bootstrap.sh --start` again | **Keeps** your file — does not overwrite |
| `bash …bootstrap.sh --restart` | **Keeps** your file — only restarts bridge to reload it |
| `nano auth.env.local` + `--restart` | Uses **your** edited passwords |
| `--force-auth` | **Regenerates** random passwords (opt-in only) |

The **bridge** container reads `auth.env.local` at startup only. After you change passwords (manual edit or `--force-auth`), restart bridge:

```bash
cd ~/open-fdd && docker compose restart bridge
```

Regenerate passwords and reload (stack already running):

```bash
bash /tmp/openfdd_edge_bootstrap.sh --force-auth --restart --show-secrets
```

Manual edit then reload:

```bash
nano ~/open-fdd/workspace/auth.env.local
bash /tmp/openfdd_edge_bootstrap.sh --restart
```

Options:

| Flag | Purpose |
|------|---------|
| `--start` | `docker compose pull && up -d` after layout; curls `http://127.0.0.1:8765/health` |
| `--image-tag TAG` | default `latest` (falls back to `2026.06.07-edge`) |
| `--repo-ref BRANCH` | branch for `compose.edge.yml` if not on `master` yet |
| `--force-auth` | regenerate `auth.env.local` (restarts bridge if stack is up) |
| `--restart` | restart bridge to reload `auth.env.local`; curls `/health` after restart |
| `--show-secrets` | print passwords at end (lab only) |

From a repo checkout: `./scripts/openfdd_edge_bootstrap.sh --start`

The script prints **BACnet NIC**, **BACNET_BIND**, and file paths — **validate** `commission.env` before polling OT devices:

```bash
nano ~/open-fdd/workspace/bacnet/commissioning/commission.env
```

{: .note }
> If you used `--start`, the stack is already up. Next step → [First login and health check](health-check).

### Manual start (optional)

Use this only if you ran bootstrap **without** `--start` and want to bring the stack up yourself:

```bash
cd ~/open-fdd
docker compose pull
docker compose up -d
docker compose ps
curl -sf http://127.0.0.1:8765/health && echo
```

Expected: **bridge**, **commission**, **mcp-rag** — all `Up`. Then → [First login and health check](health-check).

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
