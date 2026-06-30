---
title: GHCR images
parent: Operations
nav_order: 2
---

# GHCR images

## Primary runtime

```text
ghcr.io/bbartling/openfdd-edge-rust:${OPENFDD_IMAGE_TAG:-latest}
```

## Tags

| Tag | Use |
|-----|-----|
| `latest` | Early development default |
| `3.2.4` | Pinned semver |
| `v3.2.4` | Release tag alias |
| `sha-abc1234` | Short SHA traceability |

## MCP (transitional)

```text
ghcr.io/bbartling/openfdd-mcp:${OPENFDD_IMAGE_TAG:-latest}
```

Same version line as edge. MCP binary is also bundled in the edge image.

## Archived Python-era packages

These are **no longer published** by CI:

- `openfdd-bridge`
- `openfdd-commission`
- `openfdd-mcp-rag`
- `openfdd-cloud-exporter`

## Multi-arch

Images publish `linux/amd64` and `linux/arm64`. Verify:

```bash
./scripts/openfdd_rust_check_ghcr_platform.sh
docker manifest inspect ghcr.io/bbartling/openfdd-edge-rust:3.2.4
```

## OCI labels

Release images include `org.opencontainers.image.version`, `revision`, `source`, and title `Open-FDD Rust Edge`.
