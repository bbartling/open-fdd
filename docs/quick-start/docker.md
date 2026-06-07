---
title: Run with Docker images
parent: Quick Start
nav_order: 1
---

# Run with Docker images

Deploy Open-FDD on a Linux host using **published GHCR images**. No git clone or image build required on the edge host.

## Images

| GHCR image | Running service | Required |
|------------|-----------------|----------|
| `ghcr.io/bbartling/openfdd-bridge` | `bridge` | Yes |
| `ghcr.io/bbartling/openfdd-commission` | `commission` | Yes (BACnet + **default poll loop**) |
| `ghcr.io/bbartling/openfdd-mcp-rag` | `mcp-rag` | Yes (doc search sidecar) |
| `ghcr.io/bbartling/openfdd-bacnet-poll` | `bacnet-poll` | **No** — optional alternative poll driver |

Current tags: [GitHub Packages — openfdd-bridge](https://github.com/bbartling/open-fdd/pkgs/container/openfdd-bridge) (e.g. `2026.06.07-edge`).

{: .note }
> **Why only 3 containers?** BACnet **reads** run inside **commission**. The bridge runs a background **ingest** worker (CSV → feather), not a separate BACnet poll container. See [Containers](../architecture/containers).

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

Docker Engine + Compose plugin on the edge host (Ubuntu 22.04+ or similar).

## 2. Copy compose file

From a machine that has the `open-fdd` repo (or download `docker/compose.edge.yml` from GitHub):

```bash
mkdir -p ~/open-fdd/workspace
cp docker/compose.edge.yml ~/open-fdd/docker-compose.yml
```

## 3. Configure auth

Generate secrets (do **not** use `auth.env.example` values on a LAN):

```bash
# On any machine with Python:
python open-fdd/workspace/scripts/generate_auth_env.py > ~/open-fdd/workspace/auth.env.local
chmod 600 ~/open-fdd/workspace/auth.env.local
```

Commission BACnet bind — copy and edit:

```bash
mkdir -p ~/open-fdd/workspace/bacnet/commissioning
# commission.env: BACNET_BIND, BACNET_INSTANCE, discover range, etc.
```

See [BACnet network setup](../bacnet/network-setup).

## 4. Pull and start

```bash
cd ~/open-fdd
export OPENFDD_IMAGE_TAG=2026.06.07-edge

docker compose pull
docker compose up -d
docker compose ps
```

Expected services: **bridge**, **commission**, **mcp-rag**.

## 5. LAN access (optional)

Bridge listens on `127.0.0.1:8765` inside compose. For operator browsers on the building LAN, put **Caddy** (or nginx) on port 80 → `127.0.0.1:8765`, or expose 8765 through firewall:

```bash
curl -sf http://127.0.0.1:8765/health
# From another PC: http://<host-lan-ip>:8765/  (if firewall allows)
```

## Start / stop

```bash
cd ~/open-fdd
docker compose up -d
docker compose stop
docker compose restart bridge
```

{: .warning }
> Never run `docker compose down -v` or `docker volume prune` on a live site — `workspace/` is your historian and BACnet config.

## Optional fourth container

Only if you **turn off** commission’s poll loop and need a standalone driver:

```bash
docker compose --profile bacnet-poll up -d bacnet-poll
```

Do not enable while commission is also polling.

## Next steps

→ [First login and health check](health-check)  
→ [Updating the stack](updating) — backup + `docker compose pull`
