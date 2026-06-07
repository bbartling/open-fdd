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

GitHub Actions workflow **Publish Docker addons** — manual dispatch; publishes **`:latest`** only and prunes GHCR (retired `openfdd-bacnet-poll` removed; keep 3 versions per image).

Maintainer checklist:

1. Green CI on `master`
2. Run **Publish Docker addons** workflow
3. Verify `ghcr.io/bbartling/openfdd-{bridge,commission,mcp-rag}:latest`
4. Edge hosts: `docker compose pull && docker compose up -d`

Details live in `.github/workflows/` and `scripts/docker_build.sh` — not duplicated here.
