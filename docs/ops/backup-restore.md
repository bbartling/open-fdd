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

Archives default to **`~/openfdd-backups/latest`** on the edge host (overwrites each run — one rolling copy for rigorous testing).

```bash
cd ~/open-fdd
./scripts/openfdd_site_backup.sh
```

Custom location (also overwritten each run unless you use a new path):

```bash
BACKUP_ROOT=~/openfdd-backups/manual ./scripts/openfdd_site_backup.sh
```

Fast pre-upgrade backup (skips large `workspace/bacnet/polls/` CSV history; feather/model/rules kept):

```bash
BACKUP_INCLUDE_POLL_SAMPLES=0 ./scripts/openfdd_site_backup.sh
```

On **bensserver**, site packs under `edge_backup/local/<site>/<building>/` are likewise overwritten by `edge_site_backup.sh` — no timestamp pile-up during validation.

From bensserver for any edge host (Ansible — backup runs **on the edge**, no workspace transfer over Tailscale):

```bash
OPENFDD_IMAGE_TAG=3.1.3 ./scripts/upgrade_edge_site.sh --limit acme_vm_bbartling
OPENFDD_IMAGE_TAG=3.1.3 ./scripts/upgrade_edge_site.sh --limit acme_vm_bbartling --fast-backup
```

Acme wrapper (same flow):

```bash
OPENFDD_IMAGE_TAG=3.1.3 ./scripts/upgrade_acme_site.sh --fast-backup
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
5. Verify: [Deployment validation]({{ "/ops/deployment-validation/" | relative_url }})

## Safe cleanup

```bash
docker image prune -f
```

{: .warning }
> **Never on live sites:** `docker compose down -v`, `docker volume prune`, `docker system prune -a --volumes`, or deleting `workspace/`.

## Related

- [Updating the stack]({{ "/quick-start/updating/" | relative_url }})
- [Live site update]({{ "/ops/live_site_update/" | relative_url }})
