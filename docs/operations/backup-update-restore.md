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

### Local FDD + MCP smoke (low-RAM)

Central resolves historian parquet via `OPENFDD_STORAGE_URL` (preferred) or legacy `OPENFDD_PARQUET_ROOT`. For `/api/fdd/run` and MCP `openfdd_fdd_*` tools to return rows, the root must match where CSV/package ingest wrote parquet (typically `workspace/openfdd` locally or `/workspace/openfdd` on Railway).

```bash
cd ~/open-fdd

# Health + MCP initialize only (no parquet import required):
OPENFDD_SMOKE_HEALTH_ONLY=1 OPENFDD_SMOKE_TIMEOUT_SECS=60 ./scripts/release/smoke_mcp_central.sh

# Full FDD parity (empty registry OK on fresh central; import package first for non-zero rows):
OPENFDD_PARQUET_ROOT="$PWD/workspace/openfdd" ./scripts/release/smoke_mcp_central.sh
```

Scoped FDD on Railway/local: use `rule_ids` in `/api/fdd/run` POST body; avoid full-building rule floods within the default 120s smoke window.

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
4. Set `OPENFDD_PARQUET_ROOT=/workspace/openfdd` on central when using `OPENFDD_STORAGE_URL=file:///workspace/openfdd` (required for `/api/fdd/run` on imported packages)  
5. bosspi fieldbus arm64 `$SHA` with `OPENFDD_FIELDBUS_POLL_INTERVAL_SECS=60` and `OPENFDD_MQTT_PUBLISH_INTERVAL_SECS=60` (Railway only)  
6. Local firewall hub: `OPENFDD_IMAGE_TAG=$SHA ./scripts/openfdd_stack_up.sh react --no-pull` (pull first; place ACL at `deploy/mqtt/certs/acl`)  
7. Verify: `/api/health` version matches tip; volume still mounted; MQTT ingest; CSV import; FDD  

**Dual pipeline:** bosspi → Railway exclusive; bensbench local stack for on-prem. Do not point bosspi at local mqtt (or bench edge at Railway) for the parity gate.

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
