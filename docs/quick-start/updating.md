---
title: Updating the stack
parent: Quick Start
nav_order: 3
---

# Updating the stack

Upgrade GHCR images on the edge host: **backup `workspace/`, safe Docker maintenance, pull new tags, validate, purge backup**. No git pull on the host.

Full reference: [Edge site lifecycle]({{ "/quick-start/site-lifecycle/" | relative_url }}).

## Before you start

1. SSH to the edge host (`cd ~/open-fdd`).
2. Pick a tag from [GitHub Packages](https://github.com/bbartling/open-fdd/pkgs/container/openfdd-bridge) — default is **`latest`**.
3. Short maintenance window (containers restart briefly; `restart: unless-stopped` brings them back after reboot).

## One-command upgrade (recommended)

```bash
cd ~/open-fdd
./scripts/openfdd_site_backup.sh
./scripts/openfdd_site_update.sh
```

The update script prunes unused Docker images, pulls **`:latest`** (or `NEW_TAG`), recreates containers, validates `/health`, and **removes the backup directory on success**.

## Environment variables

| Variable | Default | Use |
|----------|---------|-----|
| `NEW_TAG` | `latest` | Pin GHCR tag |
| `BACKUP_INCLUDE_POLL_SAMPLES=0` | `1` | Fast backup (skip poll CSV history) |
| `SKIP_DOCKER_MAINTENANCE=1` | `0` | Skip image prune |
| `PURGE_BACKUP_AFTER_SUCCESS=0` | `1` | Keep backup after upgrade |
| `RESTORE_WORKSPACE=1` | `0` | Restore `workspace/` from backup before recreate |
| `RESTORE_FEATHER_MAX_GIB` | `200` | Historian cap on restore; `0` = all data |

## Verify

```bash
docker compose ps
curl -sf http://127.0.0.1:8765/health | jq .
ls -lah workspace/data/feather_store/
```

→ [Health check]({{ "/quick-start/health-check/" | relative_url }})

## Rollback

**Images:** restore `docker-compose.yml` from `.bak.*` snapshot or re-run with a known-good `NEW_TAG`.

**Data:** if validation failed, backup is still at `~/openfdd-backups/latest`. Restore with:

```bash
RESTORE_WORKSPACE=1 ./scripts/openfdd_site_update.sh
```

{: .warning }
> Never run `docker compose down -v`, `docker volume prune`, or delete `workspace/` on a live site.

## Next steps

→ [Edge site lifecycle]({{ "/quick-start/site-lifecycle/" | relative_url }})  
→ [Run with Docker images]({{ "/quick-start/docker/" | relative_url }})  
→ [Health check]({{ "/quick-start/health-check/" | relative_url }})
