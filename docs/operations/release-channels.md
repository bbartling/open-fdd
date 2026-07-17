---
title: Release channels
parent: Operations
nav_order: 1
---

# Release channels

Open-FDD publishes **three GHCR channels**. Only **stable** is intended for production edge sites without an explicit pin.

## Channels

| Channel | GHCR tag | Moves when | Audience |
|---------|----------|------------|----------|
| **Nightly** | `:nightly` (+ `:sha-abc1234`) | Every green `master` push | Developers, bench agents, CI |
| **Beta** | `:beta` (+ immutable semver e.g. `3.3.0-beta.1`) | Maintainer promotion after bench milestone | Pilot integrators, early OT sites |
| **Stable** | `:latest` (+ immutable semver e.g. `3.3.0`) | Maintainer promotion after beta sign-off | Production-ish edge deployments |

Every stack image (`openfdd-central`, `openfdd-ui`, `openfdd-fieldbus`,
`openfdd-mqtt`, `openfdd-mcp`) shares the same channel tags and moves together:

```text
ghcr.io/bbartling/openfdd-central:nightly
ghcr.io/bbartling/openfdd-central:beta
ghcr.io/bbartling/openfdd-central:latest
ghcr.io/bbartling/openfdd-central:3.3.0-beta.1   # immutable pin
```

`OPENFDD_IMAGE_TAG` selects the channel for a whole recipe — see
[Build recipes](build-recipes.html).

## What to pull

| Situation | Set |
|-----------|-----|
| Local dev / WSL / bench iteration | `OPENFDD_IMAGE_TAG=nightly` |
| Reproduce a specific CI build | `OPENFDD_IMAGE_TAG=sha-abc1234` |
| Friendly pilot after a beta cut | `OPENFDD_IMAGE_TAG=beta` or pin `3.3.0-beta.1` |
| Production edge (post stable sign-off) | `OPENFDD_IMAGE_TAG=latest` or pin `3.3.0` |

{: .important }
**Pin semver on OT benches** — use `3.3.0-beta.1` or `sha-*`, not floating `:nightly`, when filing a bench report.

## Promotion gates

| → Channel | Requirement |
|-----------|-------------|
| **Nightly** | Rust Edge CI green on `master` |
| **Beta** | Bench closeout on a **pinned tag** (REV_326 rigorous report), GitHub pre-release |
| **Stable** | Beta soak + no open P0s in milestone + explicit maintainer sign-off |

Open-FDD has **not** published a stable release under this model yet. Current line is **alpha / pre-beta** until the first `:beta` promotion.

## Maintainer workflows

### Nightly (automatic)

Push to `master` → workflow **Publish Open-FDD stack to GHCR** → `:nightly` + `:sha-*` on all stack images.

No semver bump on `master`. The `VERSION` file tracks the **next** beta/stable candidate only.

### Beta promotion

1. Bump `VERSION` to e.g. `3.3.0-beta.2` on `master`.
2. GitHub Actions → **Stack Release (GHCR + GitHub Release)**.
3. `version`: `3.3.0-beta.2`, `channel`: **beta**.
4. Creates GitHub **Pre-release**, moves `:beta`, publishes immutable semver tags.

### Stable promotion

1. Bump `VERSION` to e.g. `3.3.0` (no prerelease suffix).
2. **Stack Release** → `version`: `3.3.0`, `channel`: **stable**.
3. Creates GitHub Release, moves `:latest`.

## Site lifecycle

```bash
# Dev / bench
OPENFDD_IMAGE_TAG=nightly ./scripts/openfdd_stack_up.sh standalone

# Upgrade to a promoted beta
OPENFDD_IMAGE_TAG=3.3.0-beta.1 ./scripts/openfdd_stack_up.sh standalone

# Upgrade to stable
OPENFDD_IMAGE_TAG=latest ./scripts/openfdd_stack_up.sh standalone
```

See [GHCR images](ghcr-images.html) for retention, multi-arch, and diagnostics.
