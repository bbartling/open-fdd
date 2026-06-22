# Unpushed / pending GitHub work (local log)

Last updated: 2026-06-22

Git push from this environment fails: `gh` CLI not installed; HTTPS credential helper points to missing `/home/ben/bin/gh`. Run pushes from a machine with GitHub auth.

## Branches on GitHub (remote)

| Branch | Remote | Notes |
| --- | --- | --- |
| `rust-rewrite-1` | yes | Base for Rust rewrite |
| `master` | yes | Legacy Python line |
| `feature/rust-auth-security-parity` | yes | Auth/security PR branch |
| `origin/chore/docs-pdf-refresh` | stale? | Review/delete after merge |
| `origin/feat/ui-agent-readme-polish` | stale? | Review/delete after merge |
| `origin/pr-354` | stale? | Review/delete after merge |

## Local-only branches (NOT on origin)

Push when credentials work:

```bash
git push -u origin feature/rust-bench-5007-datafusion-smoke
git push -u origin feature/rust-driver-framework-react-ui-parity
git push -u origin feature/rust-edge-bootstrap-update-docs-ghcr
git push -u origin fix/ghcr-multiarch-arm64   # if still needed
```

### `feature/rust-bench-5007-datafusion-smoke` (4 commits)

```
5009d6c6 Document bench 5007 smoke workflow and ship bench CLI in Docker image.
89aa8ef8 Wire bench smoke API status and simulated CI integration test.
b17dd05c Add bench 5007 smoke runner with poll cadence and phase reports.
bfc9a00a Add Arrow historian and DataFusion SQL FDD engine for bench 5007.
```

Open PR against `rust-rewrite-1` after push.

### `feature/rust-driver-framework-react-ui-parity` (3 commits)

```
afd9de6a Document driver schema, verification flows, and extend CI smoke checks.
2cad8ab4 Rebuild driver tree UI with context menus and honest status badges.
505093d5 Add driver framework with schema validation and live-mode guards.
```

Open PR against `rust-rewrite-1` after push (rebase onto auth/bench if merging sequentially).

### `feature/rust-auth-security-parity`

Already on origin. Open/update PR against `rust-rewrite-1`.

### `feature/rust-edge-bootstrap-update-docs-ghcr`

In progress on this branch — bootstrap, GHCR, README, docs (this task).

## Local `rust-rewrite-1`

Shows `ahead 1` of origin but commit is same SHA as remote tip in some checks — verify with `git fetch && git log origin/rust-rewrite-1..rust-rewrite-1` before push.

## Local `master`

Ahead of `origin/master` (rust rewrite commits not on master remote). Do not force-push master without explicit approval.

## Recommended merge order

1. `feature/rust-auth-security-parity` → `rust-rewrite-1`
2. `feature/rust-edge-bootstrap-update-docs-ghcr` → `rust-rewrite-1`
3. `feature/rust-driver-framework-react-ui-parity` → `rust-rewrite-1` (rebase)
4. `feature/rust-bench-5007-datafusion-smoke` → `rust-rewrite-1` (rebase)

## After merges — stale branch cleanup

```bash
gh pr list --state merged
# delete merged remote branches
git push origin --delete chore/docs-pdf-refresh feat/ui-agent-readme-polish pr-354  # if merged/abandoned
```
