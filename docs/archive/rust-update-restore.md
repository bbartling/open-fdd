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

## Optional MCP sidecar (3.2.3+)

Edge update does **not** start MCP. After a successful update, pull the MCP image at the **same tag** and connect Cursor (stdio):

```bash
cd ~/open-fdd
export OPENFDD_COMPOSE_ROOT="$PWD"
export OPENFDD_IMAGE_TAG=3.2.3   # match NEW_TAG / site tag

docker compose -f docker/compose.edge.rust.yml --profile mcp-sidecar pull openfdd-mcp
```

Then configure Cursor or run interactively — see [mcp/README.md](../mcp/README.md) and README **Optional MCP sidecar**.
