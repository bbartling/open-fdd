# GitHub branch and push log

Last updated: 2026-06-22

## Merged to `rust-rewrite-1`

| PR | Branch | Status |
| --- | --- | --- |
| #356 | `feature/rust-edge-bootstrap-update-docs-ghcr` | **MERGED** |

## Open PRs (rebase onto latest `rust-rewrite-1` after doc/CI fixes)

| PR | Branch | CI notes |
| --- | --- | --- |
| #355 | `feature/rust-auth-security-parity` | manifest job failed (missing supervisor script) — fix in #360 |
| #357 | `feature/rust-driver-framework-react-ui-parity` | needs rebase + fmt/compose fixes |
| #358 | `feature/rust-bench-5007-datafusion-smoke` | needs rebase + fmt/compose fixes |
| #359 | `feature/rust-fdd-wires-sql-rule-assignments` | rebase after #360; CI fixes landed on branch |
| #360 | `feature/docs-verification-consolidation` | pending (this branch) |

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

1. #360 docs consolidation
2. #355 auth security (rebased)
3. #357 driver framework
4. #358 bench smoke (optional / can generalize docs further)
5. #359 FDD Wires
