---
title: Updating the stack
parent: Quick Start
nav_order: 3
---

# Updating the stack

## Image-only upgrade (preserve historian)

Pull a new GHCR tag **without** wiping feather data or BACnet config on the edge host:

```bash
export OPENFDD_IMAGE_TAG=<new-tag>
RUN_POST_CHECK=1 ./scripts/upgrade_edge_ghcr.sh --limit <inventory_host>
```

This sets `openfdd_docker_sync_workspace_data=false` so bind-mounted `~/open-fdd/workspace/data/` is not replaced.

## Full redeploy

When you need to sync site model, rules, or commission files from Ansible backups:

```bash
OPENFDD_IMAGE_TAG=<tag> ./deploy.sh docker --limit <inventory_host>
```

## Verify after upgrade

```bash
./scripts/stack_health_check.sh <host>
ls -la ~/open-fdd/workspace/data/feather_store/   # on edge — size should not drop to zero
docker compose -f ~/open-fdd/docker/docker-compose.yml ps
```

## Rollback

Re-deploy the previous known-good `OPENFDD_IMAGE_TAG`. Workspace data on the host survives image-only upgrades; keep backups of `workspace/data/` before major config changes.
