---
title: Edge site lifecycle
parent: Quick Start
nav_order: 4
---

# Edge site lifecycle

Professional reference for **bootstrap**, **backup**, **image update**, and **restore** on a production edge host. No git clone required on the host — scripts and GHCR images come from GitHub.

## Overview

| Phase | Script | What it does |
|-------|--------|--------------|
| **First install** | `openfdd_edge_bootstrap.sh` | Layout, compose, auth, BACnet bind, optional `docker compose up` |
| **Pre-upgrade safety** | `openfdd_site_backup.sh` | Rolling archive of `workspace/` to `~/openfdd-backups/latest` |
| **Upgrade** | `openfdd_site_update.sh` | Safe Docker prune, GHCR pull, health validation, **purge backup on success** |
| **Recovery** | `openfdd_site_update.sh` with `RESTORE_WORKSPACE=1` | Restore `workspace/` from backup (optional historian cap) |

{: .warning }
> **Never on live sites:** `docker compose down -v`, `docker volume prune`, or deleting `workspace/`. Historian data lives in the bind-mounted `workspace/data/feather_store/`.

---

## 1. Bootstrap (new host)

One-shot install from GHCR — does **not** clone the repository:

```bash
curl -fsSL -o /tmp/openfdd_edge_bootstrap.sh \
  https://github.com/bbartling/open-fdd/raw/refs/heads/master/scripts/openfdd_edge_bootstrap.sh
bash /tmp/openfdd_edge_bootstrap.sh --start
```

Creates:

| Path | Purpose |
|------|---------|
| `~/open-fdd/docker-compose.yml` | Bridge, commission, MCP stack |
| `~/open-fdd/workspace/` | Persistent site state (historian, model, auth) |
| `~/open-fdd/scripts/openfdd_site_*.sh` | Backup and update helpers |

Options: `--image-tag`, `--platform`, `--root`, `--force-auth`, `--restart`. See script header (`--help`).

Scripts auto-detect CPU (`x86_64` → `linux/amd64`, `aarch64` → `linux/arm64`). Verify GHCR manifests:

```bash
cd ~/open-fdd
./scripts/openfdd_check_ghcr_platform.sh
```

After bootstrap → [Health check]({{ "/quick-start/health-check/" | relative_url }}).

---

## 2. Backup before every upgrade

```bash
cd ~/open-fdd
./scripts/openfdd_site_backup.sh
```

Default destination: **`~/openfdd-backups/latest`** (overwritten each run — one rolling copy).

| Variable | Default | Meaning |
|----------|---------|---------|
| `BACKUP_ROOT` | `~/openfdd-backups/latest` | Output directory |
| `BACKUP_INCLUDE_POLL_SAMPLES` | `1` | Set `0` to skip large `workspace/bacnet/polls/` |
| `BACKUP_TIMEOUT_SECS` | `1800` | `tar` timeout |
| `BACKUP_TAR_XATTRS` | `0` | Set `1` for `--xattrs --acls` |

Archive: `workspace-full.tgz` plus `backup-manifest.txt` and Docker state snapshots.

---

## 3. Upgrade (recommended flow)

```bash
cd ~/open-fdd
./scripts/openfdd_site_backup.sh
./scripts/openfdd_site_update.sh
```

`openfdd_site_update.sh` performs:

1. **Verify backup** — integrity check on `workspace-full.tgz`
2. **Safe Docker maintenance** — prune stopped containers, dangling images, and **unused images** (never volumes)
3. **Pull & recreate** — all three GHCR services for `NEW_TAG` (default `latest`)
4. **Validate** — `workspace/` layout + `GET /health`
5. **Purge backup** — removes `BACKUP_ROOT` after successful validation (frees disk)

Pin a release tag:

```bash
export NEW_TAG=3.1.6
./scripts/openfdd_site_update.sh
```

| Variable | Default | Meaning |
|----------|---------|---------|
| `NEW_TAG` / `OPENFDD_IMAGE_TAG` | `latest` | GHCR image tag |
| `OPENFDD_DOCKER_PLATFORM` | `auto` | `linux/arm64`, `linux/amd64`, or auto-detect from `uname -m` |
| `BACKUP_ROOT` | `~/openfdd-backups/latest` | Backup used for validation / restore |
| `SKIP_DOCKER_MAINTENANCE` | `0` | Set `1` to skip prune |
| `PURGE_BACKUP_AFTER_SUCCESS` | `1` | Set `0` to keep backup after upgrade |
| `REQUIRE_BACKUP` | same as purge | Set `0` to upgrade without a prior backup |

If validation fails, the backup is **kept** and the script prints a restore command.

---

## 4. Restore from backup

Use when `workspace/` was corrupted, or you need to roll back **data** (not just images).

```bash
cd ~/open-fdd
RESTORE_WORKSPACE=1 ./scripts/openfdd_site_update.sh
```

This stops containers, extracts the backup, applies an optional historian cap, recreates containers, validates, and purges the backup on success.

### Historian size cap on restore

Large sites may not need full feather history on a small edge disk. Default: **keep the newest ~200 GiB** of `feather_store` shard files; drop oldest `shard-*.feather` files until under cap.

| Variable | Default | Meaning |
|----------|---------|---------|
| `RESTORE_FEATHER_MAX_GIB` | `200` | Max historian size after restore |
| `RESTORE_FEATHER_MAX_GIB=0` | — | Restore **all** feather data (no cap) |

Example — full historian restore:

```bash
RESTORE_WORKSPACE=1 RESTORE_FEATHER_MAX_GIB=0 ./scripts/openfdd_site_update.sh
```

Runtime historian caps (ongoing poll) use `OFDD_FEATHER_MAX_GIB` in bridge env — see [Configuration reference]({{ "/appendix/configuration/" | relative_url }}).

---

## 5. Fetch scripts without bootstrap

If scripts are missing:

```bash
mkdir -p ~/open-fdd/scripts
BASE=https://github.com/bbartling/open-fdd/raw/refs/heads/master/scripts
for f in openfdd_site_lib.sh openfdd_site_backup.sh openfdd_site_update.sh openfdd_check_ghcr_platform.sh; do
  curl -fsSL -o ~/open-fdd/scripts/"$f" "$BASE/$f"
done
chmod +x ~/open-fdd/scripts/openfdd_site_*.sh
```

---

## Related

- [Updating the stack]({{ "/quick-start/updating/" | relative_url }}) — operator checklist
- [Backup and restore]({{ "/ops/backup-restore/" | relative_url }}) — Ansible / bensserver paths
- [Health check]({{ "/quick-start/health-check/" | relative_url }})
- [REST API reference]({{ "/appendix/bridge_api/" | relative_url }})
