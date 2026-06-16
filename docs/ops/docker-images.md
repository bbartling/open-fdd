---
title: Docker images (GHCR)
parent: Operations
nav_order: 3
---

# Docker images (GHCR)

Full **Open-FDD edge/operator stack** — not the PyPI library.

## Images

| GHCR image | Service | Role |
|------------|---------|------|
| `ghcr.io/bbartling/openfdd-bridge` | `bridge` | API, dashboard, historian |
| `ghcr.io/bbartling/openfdd-commission` | `commission` | BACnet discover/read/poll |
| `ghcr.io/bbartling/openfdd-mcp-rag` | `mcp-rag` | MCP + doc-search sidecar |

Image name `openfdd-mcp-rag` is retained for compatibility; the container runs the unified MCP server.

## Tags

| Tag | Meaning |
|-----|---------|
| `3.0.30` | Exact release (preferred for production) |
| `3.0` | Minor alias on release tags |
| `latest` | Latest **tagged** release only |
| `edge` | Not published by default — use pinned versions on OT hosts |

```bash
export OPENFDD_IMAGE_TAG=3.0.30
docker pull ghcr.io/bbartling/openfdd-bridge:${OPENFDD_IMAGE_TAG}
docker pull ghcr.io/bbartling/openfdd-commission:${OPENFDD_IMAGE_TAG}
docker pull ghcr.io/bbartling/openfdd-mcp-rag:${OPENFDD_IMAGE_TAG}
```

## Publish

Triggered by git tag `vX.Y.Z` → workflow **Publish Docker images to GHCR** (tags `X.Y.Z`, `X.Y`, `latest`).

Manual: Actions → **Publish Docker images to GHCR** (`workflow_dispatch`) — reads `version` from `pyproject.toml` and publishes the same tags (`3.1.3`, `3.1`, `latest`). Optional `image_tag` input overrides the version.

## vs PyPI

| Need | Use |
|------|-----|
| Embed FDD in your Python/cloud job | `pip install open-fdd` |
| BACnet + UI + bridge on an edge host | GHCR images |

See [Release process]({{ "/developer/release-process/" | relative_url }}).
