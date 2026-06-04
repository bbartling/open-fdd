---
title: Docker edge deploy
nav_order: 5
---

# Docker edge deploy (Open-FDD)

Run the bridge, BACnet commission, MCP RAG, and (optionally) BACnet poll as **containers**.  
The Open-FDD **app stack does not use systemd units** on Docker edges (`openfdd-bridge`, `openfdd-bacnet-poll`, etc. are stopped and replaced by Compose).

**Caddy** (and optional host **Ollama**) stay on the host for LAN :80 and GPU access. Two small **host timers** run scheduled FDD batch and feather retention via `docker compose exec` — not separate app daemons.

Legacy **pip + rsync + systemd app units** (`./deploy.sh all`) remains for Pi/lab hosts without Docker.

## Images

| Image | Role |
|-------|------|
| `openfdd-bridge` | FastAPI + compiled React SPA |
| `openfdd-commission` | BACnet commission HTTP agent |
| `openfdd-bacnet-poll` | RPM poll driver (`network_mode: host`) |
| `openfdd-mcp-rag` | Doc search sidecar (:8090) |
| `ollama/ollama` | Optional — official image, not built in-tree |

State (feather, rules, model, `points.csv`) lives on the host under **`workspace/`**, bind-mounted into containers.

**GHCR (default on production edges):** Publish with GitHub Actions → **Publish Docker addons**, then deploy with `OPENFDD_IMAGE_TAG=<tag> ./deploy.sh docker`. See [Publish Docker addons (howto)](howto/publish_docker_addons.md). Legacy tar: `OPENFDD_DOCKER_PULL_FROM_GHCR=0` + `docker_build.sh --save`.

## Operational sync (`deploy.sh ops`)

One-shot playbook for production edges: Docker deploy, safe maintenance prune, workspace ownership fix, **POST /api/model/sync-ttl**, SPARQL tree probe (`query_engine=sparql`), feather size check, bridge log scan, HTTP insurance probes.

```bash
export SSHPASS='…'   # or secrets/acme.env.local
OPENFDD_IMAGE_TAG=2026.06.04-edge ./deploy.sh ops --limit acme_vm_bbartling
```

BRICK reads (`/api/model/tree`, `/graph`, `/scope`) use **rdflib SPARQL** on synced `workspace/data/data_model.ttl` — not grep/text search on Turtle.

## Local dev (bensserver)

```bash
cd ~/open-fdd
./scripts/docker_build.sh
./scripts/openfdd_stack.sh up          # or: docker compose -f docker/compose.dev.yml up -d
curl -s http://127.0.0.1:8765/health | jq .

# MSTP test bench (FEC 5007): host-network overlay + commission poll loop
docker compose -f docker/compose.dev.yml -f docker/compose.bench.yml up -d
./scripts/setup_local_testbench.sh     # discover, model, FDD rules

# Ollama in compose (recommended on Linux dev — host.docker.internal often times out)
docker compose -f docker/compose.dev.yml -f docker/compose.ollama-smoke.yml --profile ai up -d

# Or host Ollama only (works for ./scripts/run_local.sh; bridge-in-Docker may need the override above)
docker compose -f docker/compose.dev.yml --profile ai up -d
```

Stop: `./scripts/openfdd_stack.sh down` or `docker compose -f docker/compose.dev.yml down`

## Acme / edge deploy

### One-time: Caddy on host

If the VM has never had Caddy from Ansible:

```bash
cd infra/ansible
set -a && source secrets/acme.env.local && set +a
./deploy.sh caddy --limit acme_vm_bbartling
```

### Publish images (GitHub Actions)

1. Actions → **Publish Docker addons** → run with tag e.g. `2026.06.04-edge`.
2. Wait for green build (four images pushed to `ghcr.io/bbartling/`).

Details: [Publish Docker addons](howto/publish_docker_addons.md). Bot/feature branch cleanup: [GitHub branches and release](howto/github_branches_and_release.md).

### Deploy to Acme (pull from GHCR — default)

Pin the tag in `host_vars/acme_vm_bbartling.yml` (`openfdd_docker_pull_from_ghcr: true`, `openfdd_docker_image_tag`) or pass it on the CLI:

```bash
cd infra/ansible
set -a && source secrets/acme.env.local && set +a
OPENFDD_IMAGE_TAG=2026.06.04-edge ./deploy.sh docker --limit acme_vm_bbartling -e openfdd_docker_ollama=false
```

Ansible renders `ghcr.io/bbartling/openfdd-*:<tag>` in `docker-compose.yml`, runs **`docker compose pull`** on the VM, then **`up -d`**. No `docker/dist/*.tar.gz` copy for this path.

Use host systemd Ollama (not the compose `ollama` service). The bridge container reaches it via `host.docker.internal:11434` — ensure `sudo systemctl enable --now ollama` on the VM.

**Local `:local` builds** (`./scripts/docker_build.sh` on bensserver) are for dev only; Acme does not use them when GHCR pull is enabled.

### Legacy: tar bundle over Ansible

For lab hosts without registry access:

```bash
cd ~/open-fdd
./scripts/build_and_test.sh
OPENFDD_DOCKER_PULL_FROM_GHCR=0 OPENFDD_IMAGE_TAG=local ./scripts/docker_build.sh --save
cd infra/ansible
OPENFDD_DOCKER_PULL_FROM_GHCR=0 ./deploy.sh docker --limit acme_vm_bbartling
```

### BACnet poll on Acme

Set in `host_vars/acme_vm_bbartling.yml`:

```yaml
enable_bacnet_poll_driver: true
```

Re-run `./deploy.sh docker …` — poll container uses **`network_mode: host`** and reads `workspace/bacnet/commissioning/commission.env` (OT bind e.g. `10.200.200.185/24:47808`).

## Variables (`group_vars` / `-e`)

| Variable | Default | Purpose |
|----------|---------|---------|
| `openfdd_docker_pull_from_ghcr` | `true` (via `deploy.sh docker`) | Pull from `ghcr.io/bbartling/*`; set `false` for tar load |
| `openfdd_docker_image_tag` | required for GHCR | Must match published tag (not `local`) |
| `openfdd_docker_registry_org` | `bbartling` | GHCR org/user |
| `openfdd_docker_disable_systemd` | `true` | Stop legacy `openfdd-*` app units (bridge/mcp/poll/commission) |
| `openfdd_docker_ollama` | `true` | Compose `ollama/ollama` when `enable_ollama`; use `false` + `./deploy.sh ai` for host GPU |
| `openfdd_docker_sync_workspace_data` | `true` | Tar-sync `workspace/data` (rules); set `false` for image-only |
| `ollama_gpu_mode` | `cpu` | `gpu`/`auto` adds NVIDIA device reservation on compose Ollama |
| `openfdd_docker_prune_on_deploy` | `true` | After `compose up`, run safe image/container/network prune |
| `openfdd_docker_prune_unused_images` | `true` | `docker image prune -a` (only images not used by any container) |
| `openfdd_docker_remove_image_tar` | `true` | Delete `docker/openfdd-images-*.tar.gz` on edge after load |
| `openfdd_docker_prune_build_cache` | `false` | Optional `docker builder prune` |

## Disk maintenance (safe prune)

Each deploy may leave old `openfdd-*` image layers on disk; without cleanup, small Pi/VM disks fill up (tar path also leaves `.tar.gz` until removed).

After the stack is **up**, Ansible runs `infra/ansible/scripts/docker_edge_maintenance.sh`:

- Prunes **stopped containers**, **unused networks**, **dangling images**
- Optionally prunes **all unused images** (`docker image prune -a`) — safe because running Compose services keep their images
- Optionally removes the loaded **`openfdd-images-*.tar.gz`** on the edge host
- **Never** runs `docker volume prune` or `docker system prune --volumes` (workspace/feather is bind-mounted, not in named volumes)

Standalone maintenance (no image redeploy):

```bash
cd infra/ansible
./deploy.sh maintain --limit acme_vm_bbartling
```

Conservative (dangling images only, keep old tags and tar):

```bash
./deploy.sh maintain --limit acme_vm_bbartling \
  -e openfdd_docker_prune_unused_images=false \
  -e openfdd_docker_remove_image_tar=false
```

Skip prune during deploy:

```bash
./deploy.sh docker --limit acme_vm_bbartling -e openfdd_docker_prune_on_deploy=false
```

## What Ansible syncs (Docker path)

Unlike legacy `./deploy.sh all` (`deploy.yml`), the docker playbook does **not** rsync the full Python tree from git on every run. The **bridge image** carries the compiled SPA; **`workspace/api`** is still bind-mounted on edges for config and hotfixes (see compose template).

| Artifact | GHCR path (default) | Tar path (`OPENFDD_DOCKER_PULL_FROM_GHCR=0`) |
|----------|---------------------|-----------------------------------------------|
| App images | `docker compose pull` on edge | `docker/dist/openfdd-images-*.tar.gz` → `docker load` |
| Workspace **state** | Optional tar of `workspace/data` (rules, not feather) | Same |
| `model.json` | Copy from control | Same |
| `points.csv` | From `edge_backup/local/…` | Same |
| Env / secrets | `auth.env.local`, templates | Same |
| Compose file | Template → `~/open-fdd/docker-compose.yml` | Same |

Skip state sync on image-only deploy:

```bash
./deploy.sh docker --limit acme_vm_bbartling -e openfdd_docker_sync_workspace_data=false
```

## Host services (not Compose app containers)

| Host unit | Role |
|-----------|------|
| **caddy** | LAN :80 / TLS → `127.0.0.1:8765` |
| **openfdd-fdd-loop.timer** | Periodic `docker compose exec bridge python -m openfdd_bridge.fdd_runner --once` |
| **openfdd-feather-retention.timer** | Feather prune (host `.venv` today) |
| **ollama** (optional) | GPU inference when `openfdd_docker_ollama: false` |

**Logs:** `docker compose -f ~/open-fdd/docker-compose.yml logs -f bridge commission` — not `journalctl -u openfdd-bridge`.

## Files

```text
docker/Dockerfile              multi-target build
docker/compose.dev.yml         local bind-mount stack
scripts/docker_build.sh        build + optional tar export
infra/ansible/deploy_docker.yml
infra/ansible/edge_docker_maintenance.yml
infra/ansible/tasks/docker_maintenance.yml
infra/ansible/scripts/docker_edge_maintenance.sh
infra/ansible/templates/docker-compose.edge.yml.j2
```

## Related

- [Publish Docker addons (GHCR)](howto/publish_docker_addons.md)
- [GitHub branches and release automation](howto/github_branches_and_release.md)
- `infra/ansible/host_vars/acme_vm_bbartling.yml.example` — Acme pins
