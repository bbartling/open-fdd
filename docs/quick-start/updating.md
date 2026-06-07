---
title: Updating the stack
parent: Quick Start
nav_order: 3
---

# Updating the stack

Upgrade GHCR images on the edge host: **backup `workspace/`, pull new tags, recreate containers**. No git pull on the host.

## Before you start

1. SSH to the edge host (`cd ~/open-fdd`).
2. Pick a tag from [GitHub Packages](https://github.com/bbartling/open-fdd/pkgs/container/openfdd-bridge) — default is **`latest`**.
3. Short maintenance window (containers restart briefly; `restart: unless-stopped` brings them back after reboot).

## Fetch helper scripts (no git clone)

If you bootstrapped with `openfdd_edge_bootstrap.sh`, scripts are already under `~/open-fdd/scripts/`. Otherwise:

```bash
mkdir -p ~/open-fdd/scripts
curl -fsSL -o ~/open-fdd/scripts/openfdd_site_backup.sh \
  https://github.com/bbartling/open-fdd/raw/refs/heads/master/scripts/openfdd_site_backup.sh
curl -fsSL -o ~/open-fdd/scripts/openfdd_site_update.sh \
  https://github.com/bbartling/open-fdd/raw/refs/heads/master/scripts/openfdd_site_update.sh
chmod +x ~/open-fdd/scripts/openfdd_site_*.sh
```

## One-command upgrade (recommended)

```bash
cd ~/open-fdd
./scripts/openfdd_site_backup.sh
./scripts/openfdd_site_update.sh
```

Pulls **`:latest`** by default, verifies all three images exist on GHCR, recreates containers, and hits `/health`.

## Step by step

### 1. Backup site state

```bash
cd ~/open-fdd
./scripts/openfdd_site_backup.sh
```

Archives `workspace/` (feather, BACnet CSVs, model, auth) under `~/openfdd-backups/<timestamp>/`.

Custom backup location:

```bash
BACKUP_ROOT=~/openfdd-backups/manual ./scripts/openfdd_site_backup.sh
```

### 2. Verify images (optional)

```bash
export NEW_TAG="${NEW_TAG:-latest}"

docker manifest inspect ghcr.io/bbartling/openfdd-bridge:${NEW_TAG} >/dev/null &&
docker manifest inspect ghcr.io/bbartling/openfdd-commission:${NEW_TAG} >/dev/null &&
docker manifest inspect ghcr.io/bbartling/openfdd-mcp-rag:${NEW_TAG} >/dev/null &&
echo "All images exist for ${NEW_TAG}"
```

### 3. Pull and recreate

```bash
cd ~/open-fdd
./scripts/openfdd_site_update.sh
```

**Manual equivalent** (same as the script):

```bash
cd ~/open-fdd
docker compose pull
docker compose up -d --force-recreate
docker compose ps
curl -sf http://127.0.0.1:8765/health && echo
```

### 4. Verify

```bash
docker compose ps
curl -sf http://127.0.0.1:8765/health | jq .
tail -1 workspace/bacnet/polls/samples.csv
ls -lah workspace/data/feather_store/
```

→ [Health check](health-check)

## Dashboard UI updates

If the release changed the React UI, copy a new `workspace/api/static/app/` build onto the host before or after the image pull. Image pull alone may not change the browser bundle hash.

## Rollback

Restore `docker-compose.yml` from backup and pull again, or re-run bootstrap from a known-good `master` commit. GHCR keeps only the **three newest** versions per image; early sites should rely on **`latest`** plus `workspace/` backups.

`workspace/` is untouched by image-only upgrades.

## Safe cleanup

```bash
docker image prune -f
```

{: .warning }
> Never run `docker compose down -v`, `docker volume prune`, or delete `workspace/` on a live site.

## Next steps

→ [Run with Docker images](docker) — bootstrap a new host  
→ [Health check](health-check)
