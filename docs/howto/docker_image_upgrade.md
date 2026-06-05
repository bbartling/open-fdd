---
title: Docker image upgrade (no feather loss)
nav_order: 13
---

# Docker image upgrade without feather loss

**Yes — this is possible and is the normal GHCR upgrade path.**

Container images are disposable; **building state lives on the host OS** under `~/open-fdd/workspace/`, bind-mounted into every app container. Replacing images with `docker compose pull` + `up` does **not** delete feather history when you use the image-only deploy flags.

## What lives where

| Location on edge host | Survives image upgrade? | Contents |
|----------------------|-------------------------|----------|
| `~/open-fdd/workspace/data/feather_store/` | **Yes** | Historian (Arrow/Feather IPC files) |
| `~/open-fdd/workspace/data/model.json` | **Yes** (unless you push a new model) | BRICK site model |
| `~/open-fdd/workspace/data/rules_store.json` | **Yes** (unless overwritten by deploy) | Rule Lab saved rules |
| `~/open-fdd/workspace/bacnet/commissioning/` | **Yes** | `commission.env`, `points.csv`, poll profiles |
| `~/open-fdd/workspace/bacnet/polls/` | **Yes** | Poll CSV output |
| `~/open-fdd/workspace/auth.env.local` | **Yes** | Operator login |
| `~/open-fdd/workspace/api/` | Updated on full deploy | Bridge API + dashboard mount |
| `/etc/openfdd/bridge.secret.env` | **Yes** | Bridge secret (host file) |
| Docker image layers | Replaced | App code inside containers |

Compose bind-mount (from `docker-compose.edge.yml.j2`):

```text
~/open-fdd/workspace  →  /var/openfdd/workspace  (bridge, commission, mcp-rag, poll)
```

Data is **not** copied into the image and **not** stored in named Docker volumes for the historian.

## Image-only upgrade (recommended)

After **Publish Docker addons** pushes a new tag to `ghcr.io/bbartling/`:

```bash
cd ~/open-fdd
OPENFDD_IMAGE_TAG=2026.07.01-edge ./scripts/upgrade_edge_ghcr.sh --limit acme_vm_bbartling
```

Or manually:

```bash
cd infra/ansible
set -a && source secrets/acme.env.local && set +a
OPENFDD_IMAGE_TAG=2026.07.01-edge ./deploy.sh docker --limit acme_vm_bbartling \
  -e openfdd_docker_sync_workspace_data=false
```

**Critical flag:** `openfdd_docker_sync_workspace_data=false` — skips rsync of `workspace/data` from bensserver (which **excludes** `feather_store` anyway, but also avoids touching rules/model).

Ansible still:

- Renders `docker-compose.yml` with the new tag
- Runs `docker compose pull` + `up -d`
- Refreshes `commission.env`, `points.csv` from `edge_backup` (if present on control machine)
- Syncs `workspace/api` (bridge mount)
- Runs post-deploy checks

To skip even commission/API refresh (pure pull+restart):

```bash
OPENFDD_IMAGE_TAG=<tag> ./deploy.sh docker --limit <host> \
  -e openfdd_docker_sync_workspace_data=false \
  --tags docker
```

## Full deploy vs image-only

| Goal | Command |
|------|---------|
| **New tag, keep historian** | `upgrade_edge_ghcr.sh` or `deploy.sh docker` + `openfdd_docker_sync_workspace_data=false` |
| **Fresh building bootstrap** | `bootstrap_edge_ghcr.sh` (syncs data/rules from control + edge_backup) |
| **UI/API hotfix only** | `./deploy.sh ui --limit <host>` (legacy) or rsync `workspace/api` |

## Per-building configuration (many sites)

Each inventory host gets a **`host_vars/<inventory_name>.yml`** (private copy from `.example`):

| Variable | Purpose |
|----------|---------|
| `site_id`, `building_id` | Feather paths, FDD scope |
| `openfdd_docker_image_tag` | GHCR pin (or `OPENFDD_IMAGE_TAG` on CLI) |
| `openfdd_docker_pull_from_ghcr` | `true` for registry pull |
| `bacnet_bind_address` | OT NIC bind (`10.x/24:47808`) |
| `bacnet_commission_network_host` | `true` when commission needs host OT bind (Acme) |
| `enable_bacnet_poll_driver` | Separate `bacnet-poll` container (`network_mode: host`) |
| `bacnet_poll_interval` | Poll period (seconds) |
| `bacnet_discover_low` / `high` | Who-Is range |
| `enable_mcp`, `enable_ollama` | Sidecars / host Ollama |
| `openfdd_docker_ollama` | `false` = host systemd Ollama (Acme) |
| `feather_max_gib`, `feather_retention_days` | Historian caps |

**Commission / poll tables** (control machine, pushed on deploy):

```text
edge_backup/local/<site_id>/<building_id>/
  points.csv              # enabled BACnet points for poll
  points_discovered.csv   # inventory tree
  device_poll_profiles.csv
  rules_store.json
```

Rendered on edge as **`workspace/bacnet/commissioning/commission.env`** from `templates/commission.env.j2` (`BACNET_BIND`, `DISCOVER_*`, `SITE_ID`, `BUILDING_ID`, …).

**Acme pattern:** poll runs in **commission** container (host network), not a separate `bacnet-poll` service — `enable_bacnet_poll_driver: false` avoids double `:47808` bind.

## Pre-upgrade checklist

1. Note feather size: post-deploy check or `du -sh ~/open-fdd/workspace/data/feather_store` on edge.
2. Publish new GHCR tag (Actions → **Publish Docker addons**).
3. Pin tag in `host_vars` or `OPENFDD_IMAGE_TAG`.
4. Run **image-only** upgrade (above).
5. Confirm `/health`, `/health/stack`, BACnet poll timestamp advancing.

## Rollback

Pin previous tag in `host_vars` and re-run `upgrade_edge_ghcr.sh`. Feather files are unchanged unless you ran a full data sync or manual delete.

## Smoke test (Acme)

Validated procedure:

```bash
# Before: record feather bytes (from bensserver)
cd infra/ansible && source secrets/acme.env.local
./scripts/post_deploy_check.sh --inventory inventory.yml --limit acme_vm_bbartling | grep -i feather

# Image-only redeploy (same or new tag)
OPENFDD_IMAGE_TAG=2026.06.04-edge ./scripts/upgrade_edge_ghcr.sh --limit acme_vm_bbartling

# After: feather bytes should be >= before; check PASSED
```

## Related

- [Publish Docker addons (GHCR)](publish_docker_addons.md)
- [Docker edge deploy](../edge_deploy_docker.md)
- [Bootstrap new edge](bootstrap via `scripts/bootstrap_edge_ghcr.sh`)
