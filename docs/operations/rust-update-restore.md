# Rust edge update and restore

## Standard update

```bash
cd ~/open-fdd
./scripts/openfdd_rust_site_backup.sh
OPENFDD_IMAGE_TAG=latest ./scripts/openfdd_rust_site_update.sh
./scripts/openfdd_rust_edge_validate.sh
```

## Failure behavior

Update script keeps backup on failure. Restore:

```bash
tar -xzf ~/openfdd-backups/latest/workspace-full.tgz -C ~/open-fdd
docker compose up -d --force-recreate
```

Logs:

```bash
docker compose logs --tail=200 openfdd-bridge
```

## Image tags

| Tag | Use |
| --- | --- |
| `latest` | default GHCR |
| `3.2.0` | semver release |
| git SHA | CI publish |

Verify platform before update:

```bash
./scripts/openfdd_rust_check_ghcr_platform.sh
```
