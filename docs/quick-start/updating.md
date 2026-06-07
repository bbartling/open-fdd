---
title: Updating the stack
parent: Quick Start
nav_order: 3
---

# Updating the stack

Image upgrades on the edge host: **backup `workspace/`, pull new GHCR tags, recreate containers**. No git pull on the host.

## Before you start

1. Pick a tag from [GitHub Packages](https://github.com/bbartling/open-fdd/pkgs/container/openfdd-bridge).
2. Short maintenance window (containers restart briefly; `restart: unless-stopped` brings them back).
3. SSH to the edge host.

## 1. Backup site state

```bash
cd ~/open-fdd
./scripts/openfdd_site_backup.sh
```

Archives `workspace/` (feather, BACnet CSVs, model, auth) under `~/openfdd-backups/<timestamp>/`.

**Manual equivalent:**

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

## 2. Verify images on GHCR

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

**Manual steps:**

```bash
export OPENFDD_IMAGE_TAG=2026.06.07-edge
docker compose pull
docker compose up -d --force-recreate
docker compose ps
curl -sf http://127.0.0.1:8765/health && echo
```

Services keep `restart: unless-stopped` — no extra step after upgrade for reboot survival.

## 4. Verify

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

1. Restore `docker-compose.yml` from backup.
2. `export OPENFDD_IMAGE_TAG=<previous-tag>`
3. `docker compose pull && docker compose up -d --force-recreate`

`workspace/` is untouched by image-only upgrades.

## Safe cleanup

```bash
docker image prune -f
```

Never: `docker compose down -v`, `docker volume prune`, or deleting `workspace/`.
