---
title: Updating the stack
parent: Quick Start
nav_order: 3
---

# Updating the stack

Image-only upgrades on the edge host: **backup `workspace/`, pull new GHCR tags, recreate containers**. No git pull on the host.

## Before you start

1. Pick a published tag from [GitHub Packages](https://github.com/bbartling/open-fdd/pkgs/container/openfdd-bridge).
2. Low-traffic window (containers restart briefly).
3. SSH to the edge host.

## 1. Backup site state

Copy `scripts/openfdd_site_backup.sh` to the host (or run from a full repo checkout):

```bash
cd ~/open-fdd
./scripts/openfdd_site_backup.sh
```

This archives `workspace/` (feather, BACnet CSVs, model, auth, logs) plus compose/docker metadata under `~/openfdd-backups/<timestamp>/`.

{: .warning }
> Container processes may write `workspace/` files as root. The backup script uses `sudo tar` when needed.

**Manual one-liner** (equivalent):

```bash
cd ~/open-fdd
export BACKUP_ROOT="$HOME/openfdd-backups/$(date +%Y%m%d-%H%M%S)"
mkdir -p "$BACKUP_ROOT"
cp docker-compose.yml "$BACKUP_ROOT/docker-compose.yml.before"
docker compose ps > "$BACKUP_ROOT/docker-compose-ps-before.txt"
docker compose config --images > "$BACKUP_ROOT/docker-images-before.txt"
sudo tar --xattrs --acls -czf "$BACKUP_ROOT/workspace-full.tgz" workspace
sudo chown "$USER:$USER" "$BACKUP_ROOT/workspace-full.tgz"
echo "Backup: $BACKUP_ROOT"
```

## 2. Verify new images exist

```bash
export NEW_TAG=2026.06.07-edge

docker manifest inspect ghcr.io/bbartling/openfdd-bridge:${NEW_TAG} >/dev/null &&
docker manifest inspect ghcr.io/bbartling/openfdd-commission:${NEW_TAG} >/dev/null &&
docker manifest inspect ghcr.io/bbartling/openfdd-mcp-rag:${NEW_TAG} >/dev/null &&
echo "All images exist for ${NEW_TAG}"
```

## 3. Pull and recreate

```bash
cd ~/open-fdd
export NEW_TAG=2026.06.07-edge
./scripts/openfdd_site_update.sh
```

**Manual steps** (same as the script):

```bash
export OPENFDD_IMAGE_TAG=2026.06.07-edge
# If your compose file pins an old tag in image: lines, update them first
docker compose pull
docker compose up -d --force-recreate
docker compose ps
curl -sf http://127.0.0.1:8765/health && echo
```

## 4. Verify after upgrade

```bash
docker compose ps
curl -sf http://127.0.0.1:8765/health | jq .
ls -lah workspace/data/feather_store/    # should not be empty
tail -1 workspace/bacnet/polls/samples.csv # BACnet still moving
```

→ [Health check](health-check) for login smoke test.

## Dashboard UI updates

The bridge serves `workspace/api/static/app/` from the bind mount **before** image-baked assets. If the dashboard changed in the release, copy a new production build into `workspace/api/static/app/` (from a build machine) **before or after** the image pull. Image pull alone may not change the browser UI hash.

## Rollback

1. Restore `docker-compose.yml` from backup (`docker-compose.yml.before`).
2. `export OPENFDD_IMAGE_TAG=<previous-tag>`
3. `docker compose pull && docker compose up -d --force-recreate`

`workspace/` is unchanged by image-only upgrades — historian data survives.

## Cleanup (optional, safe)

```bash
docker image prune -f
docker builder prune -f --filter 'until=24h'
```

Never: `docker compose down -v`, `docker volume prune`, or deleting `workspace/`.
