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

## Retention and pruning (beta)

Open-FDD is in **beta** — old GHCR revisions are pruned automatically:

| Trigger | Policy |
|---------|--------|
| After **master** edge publish | Keep **2** semver releases + `latest`; delete `sha-*` and untagged versions older than **7 days** |
| After **rust-release** | Same, protecting the released version |
| **Weekly** (Sundays 06:00 UTC) | Scheduled prune (`ghcr-prune.yml`) |

Manual dry-run:

```bash
gh workflow run "Prune old GHCR images" -f dry_run=true
```

Bench sites should **pin semver** (`OPENFDD_IMAGE_TAG=3.2.4`) — not `sha-*`. Diagnose pulls:

```bash
./scripts/openfdd_ghcr_diagnose.sh 3.2.4
```

Do not delete package versions manually in the GitHub UI — use the prune workflow to avoid orphaned tags.
