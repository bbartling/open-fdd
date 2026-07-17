---
title: GHCR images
parent: Operations
nav_order: 3
---

# GHCR images

## Stack images

```text
ghcr.io/bbartling/openfdd-central:${OPENFDD_IMAGE_TAG:-nightly}
ghcr.io/bbartling/openfdd-ui:${OPENFDD_IMAGE_TAG:-nightly}
ghcr.io/bbartling/openfdd-fieldbus:${OPENFDD_IMAGE_TAG:-nightly}
ghcr.io/bbartling/openfdd-mqtt:${OPENFDD_IMAGE_TAG:-nightly}
ghcr.io/bbartling/openfdd-mcp:${OPENFDD_IMAGE_TAG:-nightly}
```

Which images a deployment pulls depends on the recipe — see
[Build recipes](build-recipes.html). Channel policy:
[Release channels](release-channels.html).

## Tag reference

| Tag | Type | Description |
|-----|------|-------------|
| `nightly` | Floating | Latest green `master` build |
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

Images publish `linux/amd64` and `linux/arm64`:

```bash
docker manifest inspect ghcr.io/bbartling/openfdd-central:nightly
```

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
