---
title: Site lifecycle
parent: Quick Start
nav_order: 3
---

# Site lifecycle

Standard operator sequence: **backup → pull/update → validate → report**.

## Backup

```bash
cd ~/open-fdd
./scripts/openfdd_rust_site_backup.sh
```

Environment:

| Variable | Effect |
|----------|--------|
| `BACKUP_INCLUDE_HISTORIAN=0` | Skip large historian samples |
| `BACKUP_INCLUDE_POLL_SAMPLES=0` | Skip poll sample blobs |

Archive: `~/openfdd-backups/latest/workspace-full.tgz`

## Update

```bash
NEW_TAG=3.2.4 ./scripts/openfdd_rust_site_update.sh
```

| Variable | Effect |
|----------|--------|
| `OPENFDD_DOCKER_PLATFORM` | `auto`, `linux/arm64`, or `linux/amd64` |
| `REQUIRE_BACKUP=1` | Default — refuse update without recent backup |
| `DRY_RUN=1` | Print plan only |

## Validate

```bash
./scripts/openfdd_rust_edge_validate.sh
curl -s http://127.0.0.1:8080/api/health | jq '{version, image_tag}'
```

## Restore workspace

```bash
tar -xzf ~/openfdd-backups/latest/workspace-full.tgz -C ~/open-fdd
docker compose up -d --force-recreate
./scripts/openfdd_rust_edge_validate.sh
```

## Safe operations

| Do | Don't |
|----|-------|
| `openfdd_rust_site_backup.sh` before updates | `docker compose down -v` |
| Pin `OPENFDD_IMAGE_TAG` for production | `docker volume prune` |
| Keep `workspace/` on durable storage | `rm -rf workspace` |

See [Operations → Backup, update, restore]({{ site.baseurl }}/operations/backup-update-restore.html) for production notes.
