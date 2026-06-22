# GitHub branch and push log

Last updated: 2026-06-22

## Merged to `rust-rewrite-1`

| PR | Branch | Status |
| --- | --- | --- |
| #356 | `feature/rust-edge-bootstrap-update-docs-ghcr` | **MERGED** |
| #360 | `feature/docs-verification-consolidation` | **MERGED** |
| #361 | `feature/rust-auth-port-rewrite` | **MERGED** (auth on correct base) |
| #359 | `feature/rust-fdd-wires-sql-rule-assignments` | **MERGED** |

## Docs cleanup (done)

Root `VERIFY_*.md` files removed. Checklists live under `docs/verification/` including [fdd-wires.md](docs/verification/fdd-wires.md).

## Open PRs

| PR | Branch | Notes |
| --- | --- | --- |
| #357 | `feature/rust-driver-framework-react-ui-parity` | Rebase onto `rust-rewrite-1` has conflicts in `main.rs`, `bacnet.rs`, `Cargo.lock` — needs manual merge |
| #358 | `feature/rust-bench-5007-datafusion-smoke` | Largely superseded by #359; close or rebase if bench-specific smoke still needed |

## Stale / review (base `master`)

| Branch | Action |
| --- | --- |
| `chore/docs-pdf-refresh` | PR #350 — separate from rust line |
| `feat/ui-agent-readme-polish` | PR #352 — separate from rust line |
| `fix/ghcr-multiarch-arm64` | Review vs `rust-ghcr.yml`; delete if superseded |
| `feature/rust-auth-security-parity` | Merged to `master` (#355) by mistake; correct auth is on `rust-rewrite-1` via #361 |

## Remote branches safe to delete (merged)

```bash
git push origin --delete feature/rust-auth-port-rewrite
git push origin --delete feature/rust-fdd-wires-sql-rule-assignments
git push origin --delete feature/docs-verification-consolidation
git push origin --delete feature/rust-edge-bootstrap-update-docs-ghcr
```

## Push command

```bash
git push -u origin <branch>   # first push
git push --force-with-lease   # after rebase
```

GitHub auth: `/home/ben/bin/gh`

## CI fixes applied this session

- Compose smoke: create `auth.env.local` before `chown`; chown only writable workspace subdirs
- FDD smoke: login via `username`/`password` from `auth.env.local` fixture
