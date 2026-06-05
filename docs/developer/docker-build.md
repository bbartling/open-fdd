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

Images: `openfdd-bridge`, `openfdd-commission`, `openfdd-bacnet-poll`, `openfdd-mcp-rag`.

## Publish to GHCR (maintainers)

GitHub Actions workflow **Publish Docker addons** — manual dispatch with a version tag.

Maintainer checklist:

1. Green CI on `master`
2. Run workflow with tag e.g. `2026.06.04-edge`
3. Verify packages at `ghcr.io/bbartling/openfdd-*`
4. Deploy to a demo edge with `OPENFDD_IMAGE_TAG=<tag>`

Details live in `.github/workflows/` and `scripts/docker_build.sh` — not duplicated here.
