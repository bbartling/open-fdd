---
title: Updating the stack
parent: Quick Start
nav_order: 3
---

# Updating the stack

Two paths depending on how you manage the edge host.

## Path A — SSH on the live VM (minimal deploy folder)

Use when the host has only `~/open-fdd/{docker,docker-compose.yml,workspace}` and **no** full git checkout.

→ **[Live site update (SSH)](../ops/live_site_update)** — backup with `sudo tar`, verify GHCR tags, edit `docker-compose.yml`, `docker compose pull` + `up -d --force-recreate`, smoke checks, rollback.

Then run the control-machine insurance check:

```bash
cd infra/ansible
./scripts/post_deploy_check.sh --limit <inventory_host>
```

## Path B — Ansible from control machine (inventory)

{: .warning }
> **Dashboard/UI changes need `deploy.sh ui` (or `upgrade_edge_full.sh`), not image pull alone.**
> The edge bind-mount `workspace/api/static/app/` overrides image-baked React assets.

**Full upgrade (UI + containers + post-deploy check):**

```bash
./scripts/build_operator_dashboard.sh prod   # if not already built
OPENFDD_IMAGE_TAG=<new-tag> ./scripts/upgrade_edge_full.sh --limit <inventory_host>
```

**Image-only** (API/commission/MCP code from GHCR, **same old UI** unless you also ran `ui`):

```bash
export OPENFDD_IMAGE_TAG=<new-tag>
RUN_POST_CHECK=1 ./scripts/upgrade_edge_ghcr.sh --limit <inventory_host>
```

Image-only sets `openfdd_docker_sync_workspace_data=false` so bind-mounted `~/open-fdd/workspace/data/` is not replaced.

## Full redeploy

When you need to sync site model, rules, or commission files from Ansible backups:

```bash
OPENFDD_IMAGE_TAG=<tag> ./deploy.sh docker --limit <inventory_host>
```

## Verify after upgrade

**Control machine:**

```bash
cd infra/ansible
./scripts/post_deploy_check.sh --limit <inventory_host>
```

**On edge host:**

```bash
ls -la ~/open-fdd/workspace/data/feather_store/   # size should not drop to zero
docker compose -f ~/open-fdd/docker-compose.yml ps
curl -sf http://127.0.0.1:8765/health
```

## Rollback

- **SSH path:** restore previous image tag in `docker-compose.yml` and recreate containers — see [rollback section](../ops/live_site_update#rollback).
- **Ansible path:** re-deploy the previous known-good `OPENFDD_IMAGE_TAG`.

Workspace data on the host survives image-only upgrades; keep backups of `workspace/` before major config changes.
