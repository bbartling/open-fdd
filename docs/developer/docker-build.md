---
title: Build Docker images
parent: Developer Guide
nav_order: 2
---

# Build Docker images

## Local build

```bash
./scripts/docker_build.sh
# Optional tar for air-gap:
./scripts/docker_build.sh --save
```

Images: `openfdd-bridge`, `openfdd-commission`, `openfdd-mcp-rag`.

## Publish to GHCR (maintainers)

GitHub Actions workflow **Publish Docker images to GHCR** — manual dispatch or git tag `vX.Y.Z`. Publishes **`pyproject.toml` version** (e.g. `3.1.3`), minor alias (`3.1`), and **`latest`**, then prunes old GHCR versions.

Maintainer checklist:

1. Green CI on `master`
2. Run **Publish Docker images to GHCR** workflow (or push tag `vX.Y.Z`)
3. Verify `ghcr.io/bbartling/openfdd-{bridge,commission,mcp-rag}:3.1.3` and `:latest`
4. Edge hosts: `OPENFDD_IMAGE_TAG=3.1.3 ./scripts/upgrade_edge_ghcr.sh --limit <host>`

Details live in `.github/workflows/` and `scripts/docker_build.sh` — not duplicated here.
