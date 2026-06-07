---
title: Run with Docker images
parent: Quick Start
nav_order: 1
---

# Run with Docker images

Deploy Open-FDD on a Linux edge host using **three published GHCR images**. No git clone or local image build on the host.

## Images

| GHCR image | Service | Role |
|------------|---------|------|
| `ghcr.io/bbartling/openfdd-bridge` | `bridge` | Operator API, dashboard, historian ingest |
| `ghcr.io/bbartling/openfdd-commission` | `commission` | BACnet discover/read/write **and poll loop** |
| `ghcr.io/bbartling/openfdd-mcp-rag` | `mcp-rag` | Doc-search sidecar |

Tags: [GitHub Packages — openfdd-bridge](https://github.com/bbartling/open-fdd/pkgs/container/openfdd-bridge) (e.g. `2026.06.07-edge`).

BACnet field reads run inside **commission**. The bridge watches `samples.csv` and loads feather — see [Containers](../architecture/containers).

## Host layout

```text
~/open-fdd/
  docker-compose.yml      # copy from repo docker/compose.edge.yml
  workspace/              # site state (bind-mounted — backup this!)
    auth.env.local
    bacnet/commissioning/commission.env
    bacnet/commissioning/points.csv
    data/feather_store/
```

## 1. Install Docker

Docker Engine + Compose plugin (Ubuntu 22.04+ or similar).

Enable Docker on boot (required for power-cycle recovery):

```bash
sudo systemctl enable docker
sudo systemctl start docker
```

## 2. Copy compose file

Download `docker/compose.edge.yml` from the repo (or copy from a build machine):

```bash
mkdir -p ~/open-fdd/workspace
cp docker/compose.edge.yml ~/open-fdd/docker-compose.yml
```

All services use `restart: unless-stopped` — they come back automatically when the host reboots **if Docker is enabled**.

## 3. Configure auth and BACnet

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(48))"  # or use generate_auth_env.py from repo
# Write workspace/auth.env.local with OFDD_AUTH_SECRET and role passwords
chmod 600 ~/open-fdd/workspace/auth.env.local
```

```bash
mkdir -p ~/open-fdd/workspace/bacnet/commissioning
# Edit commission.env: BACNET_BIND, BACNET_INSTANCE, discover range
```

See [BACnet network setup](../bacnet/network-setup).

## 4. Pull and start (first deploy)

```bash
cd ~/open-fdd
export OPENFDD_IMAGE_TAG=2026.06.07-edge

docker compose pull
docker compose up -d
docker compose ps
```

Expected: **bridge**, **commission**, **mcp-rag** — all `Up`.

```bash
curl -sf http://127.0.0.1:8765/health
```

## Long-term operation

### Survive power cycles

Compose sets `restart: unless-stopped` on every service. After a reboot:

```bash
sudo systemctl status docker    # active
cd ~/open-fdd && docker compose ps
curl -sf http://127.0.0.1:8765/health
```

If containers are not up (Docker was disabled or compose file moved):

```bash
cd ~/open-fdd
docker compose up -d
```

### Start / stop / restart (maintenance)

```bash
cd ~/open-fdd

# Idempotent — safe to run anytime; starts missing containers
docker compose up -d

# Stop stack (maintenance window; data in workspace/ is kept)
docker compose stop

# Restart one service after config change
docker compose restart commission
docker compose restart bridge

# Logs
docker compose logs -f --tail 100 commission
docker compose logs --since 30m bridge
```

{: .warning }
> Never run `docker compose down -v`, `docker volume prune`, or delete `workspace/` on a live site.

### LAN access

Bridge listens on `127.0.0.1:8765` in compose. For operator browsers on the building LAN, run **Caddy** (or nginx) on port 80 → `127.0.0.1:8765`, or expose 8765 through the host firewall.

## Next steps

→ [First login and health check](health-check)  
→ [Updating the stack](updating) — backup + `docker compose pull`
