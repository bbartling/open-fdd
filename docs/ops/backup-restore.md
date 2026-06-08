---
title: Backup and restore
parent: Operations
nav_order: 2
---

# Backup and restore

`workspace/` on the edge host is the **live site state** — feather historian, BACnet commissioning files, BRICK model, FDD rules, auth, and dashboard static bundle. Container images are replaceable; **backup `workspace/` before every upgrade.**

## Quick backup (edge host)

```bash
cd ~/open-fdd
./scripts/openfdd_site_backup.sh
```

Archives land under `~/openfdd-backups/<timestamp>/`.

Custom location:

```bash
BACKUP_ROOT=~/openfdd-backups/manual ./scripts/openfdd_site_backup.sh
```

## Manual backup (SSH)

Container processes may write files as **`root:root`** with mode **`0600`**. Use `sudo` for a full archive:

```bash
cd ~/open-fdd

export BACKUP_ROOT="$HOME/openfdd-backups/$(date +%Y%m%d-%H%M%S)"
mkdir -p "$BACKUP_ROOT"

cp docker-compose.yml "$BACKUP_ROOT/docker-compose.yml.before"
docker compose ps > "$BACKUP_ROOT/docker-compose-ps-before.txt"
docker compose config --images > "$BACKUP_ROOT/docker-images-before.txt"

sudo tar --xattrs --acls -czf "$BACKUP_ROOT/workspace-full.tgz" workspace
sudo chown "$USER:$USER" "$BACKUP_ROOT/workspace-full.tgz"

du -h "$BACKUP_ROOT/workspace-full.tgz"
```

## What to protect

| Path | Contents |
|------|----------|
| `workspace/data/feather_store/` | Feather historian |
| `workspace/bacnet/commissioning/` | `points.csv`, `commission.env` |
| `workspace/bacnet/polls/samples.csv` | Poll output |
| `workspace/data/*.json` | Model, rules store, FDD results |
| `workspace/auth.env.local` | Login secrets |
| `workspace/api/static/app/` | Dashboard bundle (if deployed separately) |

## Restore after a bad upgrade

1. Stop containers: `docker compose stop` (do **not** use `down -v`)
2. Restore `docker-compose.yml` from backup
3. If data corruption: extract selective files from `workspace-full.tgz` — model, rules, feather shards
4. `docker compose pull && docker compose up -d --force-recreate`
5. Verify: [Deployment validation](deployment-validation)

## Safe cleanup

```bash
docker image prune -f
```

{: .warning }
> **Never on live sites:** `docker compose down -v`, `docker volume prune`, `docker system prune -a --volumes`, or deleting `workspace/`.

## Related

- [Updating the stack](../quick-start/updating)
- [Live site update](live_site_update)
