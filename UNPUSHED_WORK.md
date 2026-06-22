# GitHub branch and push log

Last updated: 2026-06-22

## Merged to `rust-rewrite-1`

| PR | Branch | Status |
| --- | --- | --- |
| #356 | `feature/rust-edge-bootstrap-update-docs-ghcr` | **MERGED** |
| #360 | `feature/docs-verification-consolidation` | **MERGED** |

## Merged to `master` (wrong base — re-ported)

| PR | Branch | Notes |
| --- | --- | --- |
| #355 | `feature/rust-auth-security-parity` | Merged to `master` by mistake → **#361** ports to `rust-rewrite-1` |

## Open PRs

| PR | Branch | Notes |
| --- | --- | --- |
| #361 | `feature/rust-auth-port-rewrite` | Auth on correct base — merge next |
| #357 | `feature/rust-driver-framework-react-ui-parity` | needs merge conflict resolution |
| #358 | `feature/rust-bench-5007-datafusion-smoke` | needs rebase; generalize bench docs |
| #359 | `feature/rust-fdd-wires-sql-rule-assignments` | rebase onto #361 after merge |

## Stale / review

| Branch | Action |
| --- | --- |
| `chore/docs-pdf-refresh` | Open PR #350 on master — close or merge separately |
| `feat/ui-agent-readme-polish` | Open PR #352 on master |
| `fix/ghcr-multiarch-arm64` | Review vs `rust-ghcr.yml`; delete if superseded |
| `pr-354` | **deleted** from origin |

## Push command (all feature branches)

```bash
git push -u origin <branch>   # first push
git push --force-with-lease   # after rebase
```

GitHub auth: `/home/ben/bin/gh` (credential helper restored).

## Recommended merge order

1. #361 auth port (rust-rewrite-1)
2. #359 FDD Wires (rebase)
3. #357 driver framework (resolve conflicts)
4. #358 bench smoke (optional; keep docs generalized)
