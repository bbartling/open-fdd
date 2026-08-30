---
title: Backup, update, restore
parent: Operations
nav_order: 2
---

# Backup, update, restore

## Local stack (`workspace/`)

All persistent state for a local Compose stack lives under `workspace/`. Back it up before any image update. See [Build recipes](build-recipes.html) for the recipe/env matrix.

### Backup

```bash
cd ~/open-fdd
mkdir -p ~/openfdd-backups/latest
tar -czf ~/openfdd-backups/latest/workspace-full.tgz workspace/
```

### Update

```bash
# 1. back up workspace/ (above)
# 2. re-pull the target tag and recreate the stack
OPENFDD_IMAGE_TAG=sha-<7> ./scripts/openfdd_stack_up.sh standalone
./scripts/openfdd_health_check.sh
```

### Restore

```bash
tar -xzf ~/openfdd-backups/latest/workspace-full.tgz -C ~/open-fdd
./scripts/openfdd_stack_up.sh standalone --no-pull
./scripts/openfdd_health_check.sh
```

## Railway hub (mandatory before central re-pin)

**Primary durability:** change the **image tag only**. Keep the same Railway volume mounted at `/workspace`. Never `volume delete`, never attach a **new empty** volume for an upgrade.

| What must survive | Path on central |
|-------------------|-----------------|
| Historian Parquet | `OPENFDD_STORAGE_URL` → typically `/workspace/openfdd` |
| Packages / role maps | under `/workspace` |
| MQTT client PEMs | `/workspace/mqtt/` |

### Backup (CLI)

```bash
cd ~/open-fdd
./scripts/railway_central_workspace_backup.sh
# writes ~/openfdd-backups/railway/<UTC>/{central-workspace.tgz,mqtt-certs.tgz,README.txt}
```

Optional: `OPENFDD_BACKUP_MQTT_CERTS=0` to skip mqtt certs volume.

### Re-pin after backup

1. Tip Actions green + GHCR **Publish** success for the tip SHA  
2. `SHA=sha-<7 tip>`  
3. Re-pin **central → mqtt → web** to `$SHA` (same volume IDs)  
4. bosspi fieldbus arm64 `$SHA` with `OPENFDD_FIELDBUS_POLL_INTERVAL_SECS=60` and `OPENFDD_MQTT_PUBLISH_INTERVAL_SECS=60`  
5. Verify: `/api/health` version matches tip; volume still mounted; MQTT ingest; Overview/CSV  

### Restore if wipe

```bash
# From a backup directory:
railway ssh -s openfdd-central-cQ-F -- bash -lc 'cd /workspace && tar -xzf -' \
  < ~/openfdd-backups/railway/<UTC>/central-workspace.tgz
# then restart central / re-check health + edges
```

**Never commit** `~/openfdd-backups/` (secrets may be inside PEMs/historian).

## Manual release (maintainers)

```bash
gh workflow run "Stack Release (GHCR + GitHub Release)" \
  --ref release/v3.3.11 \
  -f version=3.3.11 \
  -f prerelease=false
```

`VERSION` file must match the input version on the selected ref.

## Never

- `docker compose down -v`
- Delete `workspace/` or Railway `/workspace` volume for an “upgrade”
- Re-pin central **without** a backup (unless human waiver)
