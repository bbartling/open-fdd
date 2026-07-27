# GitHub Actions audit — 2026-07-09

Post PR #477 merge on `master` @ `3a7dafb5`.

## Summary

| Workflow | Era | Publishes images | PR | master | Nightly | Action |
| --- | --- | --- | --- | --- | --- | --- |
| `rust-ghcr.yml` | Rust | yes (`openfdd-edge-rust:nightly`, `sha-*`) | no | yes | yes (cron) | **fix** — add schedule + smoke |
| `rust-release.yml` | Rust | yes (`beta`, `stable`, semver) | no | manual | no | **keep** |
| `rust-ghcr-mcp.yml` | Rust | yes (`openfdd-mcp`) | no | push master | no | **keep** |
| `rust-ci.yml` | Rust | no | yes | yes | no | **keep** |
| `fdd-engine-ci.yml` | Rust FDD | no | yes (path) | yes (path) | no | **keep** |
| `ci.yml` | Rust | no | yes | yes | no | **keep** (duplicate of rust-ci; consider consolidate later) |
| `appsec.yml` | both | no | yes | yes | no | **keep** |
| `security.yml` | Rust | no | yes | yes | no | **keep** |
| `docker-publish.yml` | Python | manual only | no | no | no | **archived/gated** |
| `ghcr-multiarch-publish.yml` | Python | manual only | no | no | no | **archived/gated** |
| `publish-open-fdd.yml` | Python PyPI ECM 4.x | tags `open-fdd-v*` / `v*.*.*` + dispatch | no | no | dry_run / tag | **active** (ECM-only wheel) |
| `ecm-python.yml` | Python ECM tests | path | yes | yes | no | **keep** |
| `docker-supervisor-check.yml` | ops | no | ? | ? | no | **keep** |
| `docs-pages.yml` | docs | no | yes | yes (deploy master) | no | **keep** |
| `docs-pdf.yml` | docs | no | manual | no | no | **keep** |
| `cookbook-parity.yml` | docs | no | path | path | no | **keep** |
| `ghcr-prune.yml` | ops | no | manual | no | no | **keep** |

## Per-workflow detail

### `rust-ghcr.yml` — Publish Rust edge to GHCR

- **Purpose:** Nightly Rust edge image to GHCR.
- **Triggers:** `push` master, `schedule` cron `17 7 * * *`, `workflow_dispatch`.
- **Images:** `ghcr.io/bbartling/openfdd-edge-rust:nightly`, `:sha-<short>`, optional `:nightly-YYYYMMDD`.
- **Permissions:** `contents: read`, `packages: write`.
- **Problems fixed:** missing cron; added FDD crate tests + Docker smoke in test job.
- **Does NOT publish:** `latest`, `beta`, `stable`.

### `rust-release.yml` — Rust Release

- **Purpose:** Manual beta/stable/semver promotion.
- **Triggers:** `workflow_dispatch` only.
- **Images:** `openfdd-edge-rust` + `openfdd-mcp` with channel tags.
- **Action:** **keep unchanged**.

### `fdd-engine-ci.yml` — FDD DataFusion Engine CI

- **Purpose:** fmt/clippy/test for `fdd_*` crates; registry validation; fixture smoke.
- **Triggers:** push/PR on paths under `crates/`, `sql_rules/`, etc.
- **Action:** **keep**.

### `ci.yml` / `rust-ci.yml` — Rust Edge CI

- **Purpose:** Full workspace or edge-focused tests, dashboard build, Docker compose smoke.
- **Triggers:** all push/PR.
- **Note:** Two overlapping workflows; both run on PR #477. Consolidate later.

### Python PyPI (`publish-open-fdd.yml`) — ECM 4.x

- **Purpose:** Publish slim `open-fdd` wheel (`open_fdd.ecm_engineering` only).
- **Triggers:** tags `open-fdd-v*` (preferred) or `v*.*.*`; `workflow_dispatch` dry_run.
- **Not included:** Arrow runtime / pandas FDD (those stay deleted; FDD is GHCR/SQL).
- **OIDC:** Trusted Publishing env `pypi`.

### Python-era archived workflows

- `docker-publish.yml`, `ghcr-multiarch-publish.yml` (deleted with monolith cleanup)
- **Action:** do not resurrect edge-rust PyPI/Docker publish.

## Recommended next steps

1. Merge `fix/nightly-ghcr-and-react-cutover` (cron + smoke + docs).
2. Consider consolidating `ci.yml` and `rust-ci.yml` to reduce duplicate runs.
3. Cherry-pick useful commits from `feat/release-channels-nightly-beta-stable` if docs overlap.
