---
title: Site lifecycle
parent: Quick Start
nav_order: 3
---

# Site lifecycle

Standard operator sequence: **backup → pull/update → validate → report**.
All persistent state lives under `workspace/`.

## Backup

```bash
cd ~/open-fdd
mkdir -p ~/openfdd-backups/latest
tar -czf ~/openfdd-backups/latest/workspace-full.tgz workspace/
```

## Update

Re-pull the target tag and recreate the running recipe:

```bash
OPENFDD_IMAGE_TAG=3.3.0 ./scripts/openfdd_stack_up.sh standalone
```

Pin `OPENFDD_IMAGE_TAG` (semver or `sha-*`) for production; the same tag
applies to every stack image. See [Build recipes](../operations/build-recipes.md).

## Validate

```bash
./scripts/openfdd_health_check.sh
curl -s http://127.0.0.1:8080/api/health | jq '{version, image_tag}'
```

## Restore workspace

```bash
tar -xzf ~/openfdd-backups/latest/workspace-full.tgz -C ~/open-fdd
./scripts/openfdd_stack_up.sh standalone --no-pull
./scripts/openfdd_health_check.sh
```

## Safe operations

| Do | Don't |
|----|-------|
| Back up `workspace/` before updates | `docker compose down -v` |
| Pin `OPENFDD_IMAGE_TAG` for production | `docker volume prune` |
| Keep `workspace/` on durable storage | `rm -rf workspace` |

See [Operations → Backup, update, restore]({{ site.baseurl }}/operations/backup-update-restore.html) for production notes.
