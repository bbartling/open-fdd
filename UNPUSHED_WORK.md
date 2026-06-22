# Unpushed / pending GitHub work (local log)

Last updated: 2026-06-22 (GH push restored via `/home/ben/bin/gh`)

GitHub push works after installing `gh` 2.67.0 at `/home/ben/bin/gh` (credential helper restored).

## Branches on GitHub (remote)

| Branch | Remote | Notes |
| --- | --- | --- |
| `rust-rewrite-1` | yes | Base for Rust rewrite |
| `master` | yes | Legacy Python line |
| `feature/rust-auth-security-parity` | yes | Auth/security PR branch |
| `feature/rust-edge-bootstrap-update-docs-ghcr` | yes | **PR #356** — bootstrap/GHCR/docs/CI |
| `feature/rust-bench-5007-datafusion-smoke` | yes | Pushed; open PR vs `rust-rewrite-1` |
| `feature/rust-driver-framework-react-ui-parity` | yes | Pushed; open PR vs `rust-rewrite-1` |
| `fix/ghcr-multiarch-arm64` | yes | Pushed; review/merge or delete if superseded |
| `origin/chore/docs-pdf-refresh` | stale | Open PR #350 on master — review/close |
| `origin/feat/ui-agent-readme-polish` | stale | Open PR #352 — review/close |
| `origin/pr-354` | stale | No open PR — candidate for delete |

## Local-only branches

None pending push as of last update (all feature branches above are on origin).

## PR #356 — `feature/rust-edge-bootstrap-update-docs-ghcr`

https://github.com/bbartling/open-fdd/pull/356

Commits (6 + fmt fix):

```
90267e25 Apply rustfmt and fix BACnet driver tree CI jq assertion.
0abef9fa Ignore workspace secrets and log unpushed branch status.
a8ae78b2 Refresh README and docs for Rust-first edge lifecycle.
61eaaf8a Add Rust CI and GHCR multi-arch publish workflows.
296c9907 Add Rust edge lifecycle scripts for bootstrap, backup, and update.
0fdc7adc Add multi-stage Rust edge Dockerfile and GHCR compose stack.
```

## Recommended merge order

1. `feature/rust-auth-security-parity` → `rust-rewrite-1`
2. `feature/rust-edge-bootstrap-update-docs-ghcr` (#356) → `rust-rewrite-1` (rebase onto auth after #1)
3. `feature/rust-driver-framework-react-ui-parity` → rebase
4. `feature/rust-bench-5007-datafusion-smoke` → rebase

## After merges — stale branch cleanup

```bash
gh pr list --state merged
git push origin --delete chore/docs-pdf-refresh feat/ui-agent-readme-polish pr-354  # if merged/abandoned
```
