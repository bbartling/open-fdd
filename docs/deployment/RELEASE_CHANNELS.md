# Release channels

Open-FDD Rust edge uses separate channels for automated nightly builds and manual promoted releases.

## Channels

| Tag | Source | Trigger | Mutable |
| --- | --- | --- | --- |
| `nightly` | `rust-ghcr.yml` | push to `master`, daily cron, manual | yes |
| `sha-<short>` | `rust-ghcr.yml` | same as nightly | no (immutable reference) |
| `nightly-YYYYMMDD` | `rust-ghcr.yml` | same as nightly | optional date stamp |
| `beta` | `rust-release.yml` | manual `workflow_dispatch` | yes until next beta |
| `stable` | `rust-release.yml` | manual `workflow_dispatch` | yes until next stable |
| semver (e.g. `3.3.0`) | `rust-release.yml` | manual | immutable release |

## Image

Primary production image:

```
ghcr.io/bbartling/openfdd-edge-rust
```

MCP sidecar (separate workflow):

```
ghcr.io/bbartling/openfdd-mcp
```

## What nightly includes

One Rust edge container serving:

- HTTP API at `/api/*`
- Compiled React dashboard at `/` (from `workspace/dashboard` → `frontend/`)

No separate frontend container in the default production layout.

## Legacy Python-era images

Archived workflows (`docker-publish.yml`, `ghcr-multiarch-publish.yml`) may still publish legacy images (`openfdd-bridge`, etc.) **only via manual dispatch with confirmation**. They do not publish `openfdd-edge-rust:nightly`.

## Operator guidance

- **Development / CI validation:** `openfdd-edge-rust:sha-<commit>` for a pinned build.
- **Latest master:** `openfdd-edge-rust:nightly`.
- **Production pilot:** promote via `rust-release.yml` → `beta`, then `stable`.
