---
title: Backup, update, restore
parent: Operations
nav_order: 1
---

# Backup, update, restore

## Backup

```bash
cd ~/open-fdd
./scripts/openfdd_rust_site_backup.sh
```

Output: `~/openfdd-backups/latest/workspace-full.tgz`

## Update

```bash
./scripts/openfdd_rust_site_backup.sh
NEW_TAG=3.2.4 ./scripts/openfdd_rust_site_update.sh
./scripts/openfdd_rust_edge_validate.sh
```

`REQUIRE_BACKUP=1` (default) blocks update without a recent backup.

## Restore

```bash
tar -xzf ~/openfdd-backups/latest/workspace-full.tgz -C ~/open-fdd
docker compose up -d --force-recreate
./scripts/openfdd_rust_edge_validate.sh
```

## Manual release (maintainers)

```bash
gh workflow run "Rust Release (GHCR + GitHub Release)" \
  --ref release/v3.2.4 \
  -f version=3.2.4 \
  -f prerelease=false
```

`VERSION` file must match the input version on the selected ref.

## Never

- `docker compose down -v`
- Delete `workspace/`
