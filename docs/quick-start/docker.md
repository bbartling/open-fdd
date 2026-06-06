---
title: Run with Docker images
parent: Quick Start
nav_order: 1
---

# Run with Docker images

## Images (GHCR)

| Image | Role |
|-------|------|
| `ghcr.io/bbartling/openfdd-bridge` | FastAPI + React dashboard |
| `ghcr.io/bbartling/openfdd-commission` | BACnet discover / read / write agent |
| `ghcr.io/bbartling/openfdd-bacnet-poll` | Historian poll driver (host network) |
| `ghcr.io/bbartling/openfdd-mcp-rag` | Optional doc-search sidecar |

Check [GitHub Packages](https://github.com/bbartling/open-fdd/pkgs/container/openfdd-bridge) for current tags (e.g. `2026.06.07-edge`).

## Option A — Ansible deploy (edge VM)

From your **control machine** (laptop or CI runner with SSH to the edge host):

```bash
git clone https://github.com/bbartling/open-fdd.git && cd open-fdd

# One-time: build dashboard assets if not in the image tag you use
./scripts/build_operator_dashboard.sh prod

# Set image tag from a published GHCR release
export OPENFDD_IMAGE_TAG=2026.06.07-edge

# Deploy (requires inventory + host_vars — see infra/ansible/inventory.example.yml)
cd infra/ansible
export SSHPASS='your-ssh-password'   # or use SSH keys
./deploy.sh docker --limit <inventory_host>
```

Host vars should set `openfdd_docker_pull_from_ghcr: true`. Site BACnet bind, model, and rules sync from `infra/ansible` templates and `edge_backup/local/<site>/`.

**Bootstrap helper** (docker → Caddy → optional AI → ops check):

```bash
OPENFDD_IMAGE_TAG=2026.06.07-edge ./scripts/bootstrap_edge_ghcr.sh --limit <inventory_host>
```

## Option B — Local trial (compose on one machine)

For a quick lab trial without Ansible:

```bash
git clone https://github.com/bbartling/open-fdd.git && cd open-fdd
cp workspace/auth.env.example workspace/auth.env.local   # edit passwords
./scripts/docker_build.sh    # or pull GHCR tags into compose via env
./scripts/openfdd_stack.sh up
```

Open `http://127.0.0.1:8765/` (bridge) or `http://127.0.0.1/` if Caddy is installed locally.

## Required configuration

| File | Purpose |
|------|---------|
| `workspace/auth.env.local` | Operator / integrator login and `OFDD_AUTH_SECRET` |
| `workspace/bacnet/commissioning/commission.env` | BACnet bind IP, instance, discover range |
| `workspace/data/` | Bind-mounted historian, rules, model (created on first run) |

Copy from `*.example` files in the repo. Never commit real passwords.

## Start / stop

```bash
# Ansible edge: re-run deploy or on host:
cd ~/open-fdd/docker && docker compose up -d

# Local dev:
./scripts/openfdd_stack.sh up
./scripts/openfdd_stack.sh down
```

## After first deploy

→ [First login and health check](health-check)  
→ [Updating the stack](updating) — Ansible from control machine  
→ [Live site update (SSH)](../ops/live_site_update) — tag bump on minimal `~/open-fdd/` folder
