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

### Build images + bundle on bensserver

```bash
cd ~/open-fdd
./scripts/build_and_test.sh          # or build_operator_dashboard.sh prod
./scripts/docker_build.sh --save     # writes docker/dist/openfdd-images-local.tar.gz
```

### Push to Acme via Ansible

```bash
cd infra/ansible
set -a && source secrets/acme.env.local && set +a
./deploy.sh docker --limit acme_vm_bbartling -e openfdd_docker_ollama=false
```

Use host systemd Ollama (not the compose `ollama` service). The bridge container reaches it via `host.docker.internal:11434` — ensure `sudo systemctl enable --now ollama` on the VM.

Optional tag:

```bash
OPENFDD_IMAGE_TAG=2026.06.01 ./scripts/docker_build.sh --save
./deploy.sh docker --limit acme_vm_bbartling -e openfdd_docker_image_tag=2026.06.01
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
| `openfdd_docker_image_tag` | `local` | Image tag in compose |
| `openfdd_docker_disable_systemd` | `true` | Stop legacy `openfdd-*` app units (bridge/mcp/poll/commission) |
| `openfdd_docker_ollama` | `true` | Compose `ollama/ollama` when `enable_ollama`; use `false` + `./deploy.sh ai` for host GPU |
| `openfdd_docker_sync_workspace_data` | `true` | Tar-sync `workspace/data` (rules); set `false` for image-only |
| `ollama_gpu_mode` | `cpu` | `gpu`/`auto` adds NVIDIA device reservation on compose Ollama |
| `openfdd_docker_prune_on_deploy` | `true` | After `compose up`, run safe image/container/network prune |
| `openfdd_docker_prune_unused_images` | `true` | `docker image prune -a` (only images not used by any container) |
| `openfdd_docker_remove_image_tar` | `true` | Delete `docker/openfdd-images-*.tar.gz` on edge after load |
| `openfdd_docker_prune_build_cache` | `false` | Optional `docker builder prune` |

## Disk maintenance (safe prune)

Each `./deploy.sh docker` run loads a new image bundle; without cleanup, old `openfdd-*` layers and the `.tar.gz` fill small Pi/VM disks.

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

**No Python/API git rsync** — unlike legacy `./deploy.sh all` (`deploy.yml`), the docker playbook does **not** push `workspace/api`, `open_fdd`, or built UI from source trees.

| Artifact | Mechanism | Purpose |
|----------|-----------|---------|
| App images | `docker/dist/openfdd-images-*.tar.gz` → `docker load` | Bridge, commission, poll, MCP |
| Workspace **state** | Optional tar of `workspace/data` (rules, not feather) | Rule store, configs |
| `model.json` | Single file copy from control | Site BRICK model |
| `points.csv` | From `edge_backup/local/…` | Commission table |
| Env / secrets | `auth.env.local`, templates | Login, BACnet bind, bridge secret |
| Compose file | Template render | Stack definition |

Skip state sync on image-only deploy:

```bash
./deploy.sh docker --limit acme_vm_bbartling -e openfdd_docker_sync_workspace_data=false
```

**Future:** edge `docker compose pull` from GHCR (see [publish Docker addons](howto/publish_docker_addons.md)) — no tar over SSH.

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

## Next steps (registry)

Replace `docker save` / `copy` / `load` with a private registry pull when you have many sites:

```bash
docker tag openfdd-bridge:local registry.example/openfdd-bridge:1.2.3
docker push registry.example/openfdd-bridge:1.2.3
```

Ansible then runs `docker compose pull` instead of loading a tar.
