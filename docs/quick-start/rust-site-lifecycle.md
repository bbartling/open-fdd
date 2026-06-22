# Rust site lifecycle

## Backup

```bash
cd ~/open-fdd
./scripts/openfdd_rust_site_backup.sh
```

Environment:

- `BACKUP_INCLUDE_HISTORIAN=0` — skip large historian samples
- `BACKUP_INCLUDE_POLL_SAMPLES=0` — skip poll sample blobs

Archive: `~/openfdd-backups/latest/workspace-full.tgz`

## Update

```bash
NEW_TAG=3.2.0 ./scripts/openfdd_rust_site_update.sh
```

Environment:

- `OPENFDD_DOCKER_PLATFORM=auto|linux/arm64|linux/amd64`
- `REQUIRE_BACKUP=1` (default)
- `DRY_RUN=1` — print plan only
- `PURGE_BACKUP_AFTER_SUCCESS=1` — remove backup after successful update

## Validate

```bash
./scripts/openfdd_rust_edge_validate.sh
```

## Restore workspace

```bash
tar -xzf ~/openfdd-backups/latest/workspace-full.tgz -C ~/open-fdd
docker compose up -d --force-recreate
./scripts/openfdd_rust_edge_validate.sh
```

## Safe operations only

Never:

- `docker compose down -v`
- `docker volume prune`
- `rm -rf workspace`
