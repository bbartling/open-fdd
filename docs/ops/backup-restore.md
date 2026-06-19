---
title: Backup and restore
parent: Operations
nav_order: 2
---

# Backup and restore

`workspace/` on the edge host is the **live site state** — feather historian, BACnet commissioning files, BRICK model, FDD rules, auth, and dashboard static bundle. Container images are replaceable; **backup `workspace/` before every upgrade.**

Canonical operator flow: [Edge site lifecycle]({{ "/quick-start/site-lifecycle/" | relative_url }}).

## Quick backup (edge host)

```bash
cd ~/open-fdd
./scripts/openfdd_site_backup.sh
```

Archives default to **`~/openfdd-backups/latest`** (overwrites each run).

Fast pre-upgrade backup (skips large `workspace/bacnet/polls/` CSV history):

```bash
BACKUP_INCLUDE_POLL_SAMPLES=0 ./scripts/openfdd_site_backup.sh
```

Custom location:

```bash
BACKUP_ROOT=~/openfdd-backups/manual ./scripts/openfdd_site_backup.sh
```

## Upgrade + automatic backup purge

After a successful `./scripts/openfdd_site_update.sh`, the backup directory is **removed** by default once health and workspace layout checks pass. Set `PURGE_BACKUP_AFTER_SUCCESS=0` to retain archives.

## Restore from backup

```bash
cd ~/open-fdd
RESTORE_WORKSPACE=1 ./scripts/openfdd_site_update.sh
```

Default historian cap on restore: **200 GiB** of newest feather shards. Full restore:

```bash
RESTORE_WORKSPACE=1 RESTORE_FEATHER_MAX_GIB=0 ./scripts/openfdd_site_update.sh
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

## Ansible / bensserver

From bensserver for any edge host (backup runs **on the edge**, no workspace transfer over Tailscale):

```bash
OPENFDD_IMAGE_TAG=3.1.3 ./scripts/upgrade_edge_site.sh --limit acme_vm_bbartling
OPENFDD_IMAGE_TAG=3.1.3 ./scripts/upgrade_edge_site.sh --limit acme_vm_bbartling --fast-backup
```

## Safe cleanup

Handled automatically by `openfdd_site_update.sh` (stopped containers, dangling/unused images). Manual:

```bash
docker image prune -f
```

{: .warning }
> **Never on live sites:** `docker compose down -v`, `docker volume prune`, `docker system prune -a --volumes`, or deleting `workspace/`.

## Related

- [Edge site lifecycle]({{ "/quick-start/site-lifecycle/" | relative_url }})
- [Updating the stack]({{ "/quick-start/updating/" | relative_url }})
- [Live site update]({{ "/ops/live_site_update/" | relative_url }})
