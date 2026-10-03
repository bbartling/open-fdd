---
title: GHCR images
parent: Operations
nav_order: 3
nav_exclude: true

---

# GHCR images

## Stack images

```text
ghcr.io/bbartling/openfdd-central:${OPENFDD_IMAGE_TAG:-nightly}
ghcr.io/bbartling/openfdd-web:${OPENFDD_IMAGE_TAG:-nightly}
ghcr.io/bbartling/openfdd-fieldbus:${OPENFDD_IMAGE_TAG:-nightly}
ghcr.io/bbartling/openfdd-mqtt:${OPENFDD_IMAGE_TAG:-nightly}
ghcr.io/bbartling/openfdd-mcp:${OPENFDD_IMAGE_TAG:-nightly}
```

Cloud platforms such as Railway need pull access to every selected image. For the simplest open-source deployment, make the GHCR packages public; otherwise configure the platform with explicit registry credentials. A `401 Unauthorized` from an unauthenticated manifest request usually means the package is still private. New GHCR packages can default to private, so re-check visibility when adding an image. See [Railway deployment](RAILWAY_DEPLOYMENT.md).

Which images a deployment pulls depends on the recipe — see
[Build recipes](build-recipes.html). Channel policy:
[Release channels](release-channels.html).

## Tag reference

| Tag | Type | Description |
|-----|------|-------------|
| `nightly` | Floating | Latest green `master` build (pointer — **not** proof of newest) |

Resolve newest by OCI config `created` (not tag name):

```bash
./scripts/ghcr_newest_by_created.py openfdd-central openfdd-web
```

Unmerged `frontend/web` is never inside `openfdd-web:sha-*`. Serve a local
bundle and run `./scripts/openfdd_demo_gate.sh --local-web` before any login
link. `openfdd_stack_up.sh` refuses GHCR web when `frontend/web` drifted
(`OPENFDD_ALLOW_STALE_GHCR_WEB=1` to override).
| `beta` | Floating | Last promoted beta pre-release |
| `latest` | Floating | Last promoted **stable** release |
| `3.3.0-beta.1` | Immutable | Pinned beta semver |
| `3.3.0` | Immutable | Pinned stable semver |
| `v3.3.0` | Immutable | Release tag alias |
| `sha-abc1234` | Immutable | Short git SHA (traceability) |

## MCP server

```text
ghcr.io/bbartling/openfdd-mcp:${OPENFDD_IMAGE_TAG:-nightly}
```

Slim Rust image; talks to central via `OPENFDD_API_BASE`. Same channel tags as the rest of the stack.

## Multi-arch

| Image | Platforms |
|-------|-----------|
| `openfdd-central` | `linux/amd64`, `linux/arm64` (Recipe 2) |
| `openfdd-web` | `linux/amd64`, `linux/arm64` (Recipe 2) |
| protocol / fieldbus / split connectors | `linux/amd64`, `linux/arm64` |
| `openfdd-mqtt` | **`linux/amd64` only** (Recipe 1 cloud hub) |

```bash
docker manifest inspect ghcr.io/bbartling/openfdd-central:nightly
docker manifest inspect ghcr.io/bbartling/openfdd-web:nightly
```

arm64 Pi Recipe 2 remains Soft-OPEN until a tip’s central+web manifests include arm64 and a Pi boots them.

## OCI labels

Release images include `org.opencontainers.image.version`, `revision`, `source`, and per-image titles (e.g. `Open-FDD Central`).

## Retention

| Trigger | Policy |
|---------|--------|
| After **master** publish | Protect `nightly`, `beta`, `latest`; keep 3 semver lines; prune old `sha-*` > 7 days |
| After **rust-release** | Same, protecting the released semver |
| **Weekly** (Sundays 06:00 UTC) | Scheduled prune (`ghcr-prune.yml`) |

Manual dry-run:

```bash
gh workflow run "Prune old GHCR images" -f dry_run=true
```

Diagnose pulls:

```bash
./scripts/openfdd_ghcr_diagnose.sh nightly
./scripts/openfdd_ghcr_diagnose.sh 3.3.0-beta.1
```

Do not delete package versions manually in the GitHub UI — use the prune workflow.