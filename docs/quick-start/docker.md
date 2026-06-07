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

## 1. Install Docker

Docker Engine + Compose plugin (Ubuntu 22.04+ or similar).

Enable Docker on boot (required for power-cycle recovery):

```bash
sudo systemctl enable docker
sudo systemctl start docker
```

### Validate Docker, Compose, and your user

Run on the edge host **before** pulling Open-FDD images:

```bash
# Engine + Compose plugin (v2 — "docker compose", not legacy "docker-compose")
docker --version
docker compose version

# Daemon running and enabled on boot
systemctl is-active docker    # expect: active
systemctl is-enabled docker   # expect: enabled

# Your login user in the docker group (run docker without sudo)
groups
id
# expect "docker" in the group list

# Non-root smoke test
docker ps
docker run --rm hello-world
```

If `docker ps` says *permission denied*, add your user to the `docker` group and **log out/in** (or `newgrp docker`):

```bash
sudo usermod -aG docker "$USER"
newgrp docker   # or SSH logout/login
docker ps       # should work without sudo
```

Pull a public image to confirm registry access (GHCR pulls use the same path):

```bash
docker pull hello-world
```

## 2. Create site layout and compose file

One-time setup on the edge host — creates `~/open-fdd/` and downloads `docker-compose.yml` (no git clone).

```bash
set -euo pipefail
export OPENFDD_ROOT="${OPENFDD_ROOT:-$HOME/open-fdd}"
# compose.edge.yml: use master after release merge; until then use the docs branch:
export OPENFDD_REPO_REF="${OPENFDD_REPO_REF:-fix/security-hardening-log-rotation}"
export OPENFDD_GITHUB_RAW="https://github.com/bbartling/open-fdd/raw/refs/heads/${OPENFDD_REPO_REF}"

# Directory tree (bind-mounted site state — backup this folder before upgrades)
mkdir -p "${OPENFDD_ROOT}/workspace/bacnet/commissioning"
mkdir -p "${OPENFDD_ROOT}/workspace/bacnet/polls"
mkdir -p "${OPENFDD_ROOT}/workspace/data/feather_store"
mkdir -p "${OPENFDD_ROOT}/workspace/data/playground"
mkdir -p "${OPENFDD_ROOT}/workspace/logs"
mkdir -p "${OPENFDD_ROOT}/workspace/api/static/app"

# Compose file (-f fails loudly on 404)
curl -fsSL -o "${OPENFDD_ROOT}/docker-compose.yml" \
  "${OPENFDD_GITHUB_RAW}/docker/compose.edge.yml"
test -s "${OPENFDD_ROOT}/docker-compose.yml"

# BACnet starter config (commission.env.example is on master — use master for this file)
curl -fsSL -o "${OPENFDD_ROOT}/workspace/bacnet/commissioning/commission.env" \
  "https://raw.githubusercontent.com/bbartling/open-fdd/master/bacnet_toolshed/commission.env.example"

# Empty poll output + points registry (fill points.csv after commissioning)
touch "${OPENFDD_ROOT}/workspace/bacnet/polls/samples.csv"
touch "${OPENFDD_ROOT}/workspace/bacnet/commissioning/points.csv"

cd "${OPENFDD_ROOT}"
tree -L 4 2>/dev/null || find . -maxdepth 4 -type d | sort
ls -la docker-compose.yml workspace/bacnet/commissioning/commission.env
```

Expected layout:

```text
~/open-fdd/
  docker-compose.yml
  workspace/
    auth.env.local              # step 3 — you create this
    bacnet/commissioning/
      commission.env            # downloaded — edit BACnet bind
      points.csv                # empty — add enabled poll rows
    bacnet/polls/
      samples.csv               # created empty — commission appends here
    data/feather_store/         # historian (grows at runtime)
    logs/                       # audit/error JSONL (optional)
```

If `curl` returns **404** for `compose.edge.yml`, the file is not on `master` yet — set `OPENFDD_REPO_REF=fix/security-hardening-log-rotation` (or your release branch) and re-run only the compose `curl` line.

All services use `restart: unless-stopped` — they come back automatically when the host reboots **if Docker is enabled**.

## 3. Configure auth and BACnet

Create `auth.env.local` (do not skip — `chmod` alone will fail if the file does not exist):

```bash
export OPENFDD_ROOT="${OPENFDD_ROOT:-$HOME/open-fdd}"
python3 <<'PY' > "${OPENFDD_ROOT}/workspace/auth.env.local"
import secrets, string
alpha = string.ascii_letters + string.digits + "!@#$%^&*-_"
def pw(n=24):
    import random
    return "".join(secrets.choice(alpha) for _ in range(n))
print(f"OFDD_AUTH_SECRET={secrets.token_urlsafe(48)}")
print("OFDD_OPERATOR_USER=operator")
print(f"OFDD_OPERATOR_PASSWORD={pw()}")
print("OFDD_INTEGRATOR_USER=integrator")
print(f"OFDD_INTEGRATOR_PASSWORD={pw()}")
print("OFDD_AGENT_USER=agent")
print(f"OFDD_AGENT_PASSWORD={pw()}")
PY
chmod 600 "${OPENFDD_ROOT}/workspace/auth.env.local"
echo "Wrote ${OPENFDD_ROOT}/workspace/auth.env.local (store securely; not in git)"
```

Edit `~/open-fdd/workspace/bacnet/commissioning/commission.env` (`BACNET_BIND`, `BACNET_INSTANCE`, discover range) and add enabled rows to `points.csv`.

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
