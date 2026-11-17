# Grok 5.0.21 checkpoint (Python/PyPI tooling lane + independent acceptance)

Grok-maintained. Claude owns `plans/release-5.0.21.md` and folds accepted receipts in from here.
Coordination is by PR comment and SHA only. Times are America/Chicago.

## Identity and location

- Agent: Grok, working in its own isolated clone (separate `.git`, no alternates, no worktree links to the
  canonical checkout). Disposable venvs, worktrees, the LBNL cache and logs live beside that clone in the OS temp
  directory. The canonical checkout was never read for writing, switched or tested in.
- Base: `origin/release/5.0.21` = `7642f407`. Python package `4.5.11`, app `5.0.21`.
- Checkpoint branch: `grok/5.0.21-pypi-tooling`.

## Reviews and acceptance receipts (2026-11-17)

| PR | Head | Verdict | Receipt |
|---|---|---|---|
| #1674 ledger + CI routing | `7cbc96a6` | ready to merge, notes only | https://github.com/bbartling/open-fdd/pull/1674#issuecomment-6962899508 |
| #1675 tutorial links | `0f85036a` | ready to merge (merge after #1674 so the Pages build runs on release) | https://github.com/bbartling/open-fdd/pull/1675#issuecomment-6962900090 |
| #1676 #1669 RH alias | `723d90d3` | independent acceptance PASS; marked ready for review | https://github.com/bbartling/open-fdd/pull/1676#issuecomment-6963418532 |

Measured #1676 results:
- Full Python suite: 531 passed, 8 skipped (environment-only).
- Node: 770/770 pass.
- Typecheck is clean, and all 10 generator checks pass.
- `rh-unit-alias` regression: 5/5 pass here, 5/5 fail on base.
- Own consumer fixture (two sensors on one role, irregular cadence, 4 sweeps × PGlite/SQLite): 82/82 checks pass.
- pandas public API: `percent_0_100` gives PASS 0.0 h on base and FAULT 2.95 h here.

Open observation for Claude: in the pandas sweep, an unassessable RH unit returns PASS 0.0 rather than unassessed
(this predates #1676).

## Own tooling PRs (all into `release/5.0.21`; need a non-author review/test; Grok does not merge)

| PR | Branch | Head | Issue | Scope |
|---|---|---|---|---|
| #1677 | `grok/1666-modegated-refit` | `254ccab8` | Refs #1666 | ModeGated clean/atomic refit, failed fit unusable, `assessment()` reasons, fit receipt |
| #1678 | `grok/1665-explicit-training` | `bb1dc35d` | Refs #1665 | `detect` requires explicit training source; phase labels; evaluation-only counts; training receipt |
| #1679 | `grok/1666-elapsed-coverage` | `6c65368d` | Refs #1666 | elapsed-time window eligibility, `window_coverage()`, benchmark excluded coverage; full LBNL benchmark 56/56 scores unchanged |

Shared-file note: #1677, #1678 and #1679 each add tests at different anchors in `tests/test_ml_fdd.py`. If
merge order causes a textual conflict, Grok will update its own branch on request.

## Issue states (Grok lane)

| # | State | Notes |
|---|---|---|
| 1665 | PR READY (#1678) | acceptance 1-5 mapped to named tests |
| 1666 | PR READY partial (#1677, #1679) | still open: assessed/unassessed contract for PCA/gray-box/CLI JSON (acceptance 1, 6) |
| 1656, 1659, 1652-1655, 1657, 1658, 1660-1662, 1667 | OPEN/OWNED | next in sequence |
| 1663 | OPEN | tracker; closes only after children and 4.5.12 release evidence |
| 1669 (Claude) | INDEPENDENTLY VERIFIED on `723d90d3` | stays open until integrated and released |

## Next actions

See the latest handoff comment on the checkpoint PR.
