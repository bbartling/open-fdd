---
title: Backup, update, restore
parent: Operations
nav_order: 2
---

# Backup, update, restore

All persistent state lives under `workspace/`. Back it up before any image
update. See [Build recipes](build-recipes.html) for the recipe/env matrix.

## Backup

```bash
cd ~/open-fdd
mkdir -p ~/openfdd-backups/latest
tar -czf ~/openfdd-backups/latest/workspace-full.tgz workspace/
```

## Update

```bash
# 1. back up workspace/ (above)
# 2. re-pull the target tag and recreate the stack
OPENFDD_IMAGE_TAG=3.3.0 ./scripts/openfdd_stack_up.sh standalone
./scripts/openfdd_health_check.sh
```

## Restore

```bash
tar -xzf ~/openfdd-backups/latest/workspace-full.tgz -C ~/open-fdd
./scripts/openfdd_stack_up.sh standalone --no-pull
./scripts/openfdd_health_check.sh
```

## Manual release (maintainers)

```bash
gh workflow run "Stack Release (GHCR + GitHub Release)" \
  --ref release/v3.3.0 \
  -f version=3.3.0 \
  -f prerelease=false
```

`VERSION` file must match the input version on the selected ref.

## Never

- `docker compose down -v`
- Delete `workspace/`
