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

Stacked PRs keep base `release/5.0.21`; review only the top commit named in each body. Merge a stack bottom-up.

| PR | Branch | Head | Issue | Stack | Scope |
|---|---|---|---|---|---|
| #1677 | `grok/1666-modegated-refit` | `254ccab8` | Refs #1666 | - | ModeGated atomic refit, `assessment()` reasons, fit receipt |
| #1678 | `grok/1665-explicit-training` | `bb1dc35d` | Refs #1665 | - | `detect` needs an explicit training source; phase labels; evaluation-only counts |
| #1679 | `grok/1666-elapsed-coverage` | `6c65368d` | Refs #1666 | - | elapsed-time window eligibility, `window_coverage()`, excluded coverage |
| #1681 | `grok/1656-activity-policy` | `b22c0f60` | Refs #1656 | - | one activity policy for screen and ml detect |
| #1682 | `grok/1659-method-roles` | `60b01e87` | Refs #1659 | - | `open-fdd-ml methods`, single-zone gray-box; LBNL rerun identical (receipt on PR) |
| #1683 | `grok/1661-run-all-context` | `a73f5912` | Refs #1661 | - | explicit equipment context for run_all/run_rule, `summarize()` |
| #1684 | `grok/1654-screen-defaults` | `c37e3af7` | Refs #1654 #1658 | on #1681 | screen defaults run on what is installed; iforest opt-in |
| #1685 | `grok/1655-screen-json` | `932142cc` | Refs #1655 | on #1684 | `summary.json`, `--json`, `--no-plots`, `--tz` |
| #1686 | `grok/1652-make-folder` | `d4dd7191` | Refs #1652 | on #1682 | `open-fdd-ml make-folder`, device-folder format |
| #1687 | `grok/1660-roles-used` | `d7dfd77e` | Refs #1660 | on #1678 | roles used/missing, per-row flag explanations |
| #1688 | `grok/1657-mad-floor` | `9b7d0291` | Refs #1657 | on #1685 | MAD resolution floor + near_constant skip; quantized damper 1230 -> 0 min/week; LBNL mad FPR 58.1 -> 57.1 % |
| #1689 | `grok/1662-pypi-docs` | `22974981` | Refs #1662 | on #1688 | absolute README links (test), wheel examples, no-NF note, download/seed help |
| #1690 | `grok/1653-nf-export-folder` | `ab7daf55` | Refs #1653 | - | `open-fdd-nf export-folder` (mock NF tested) |
| #1691 | `grok/1667-episode-review` | `dd64c89c` | Refs #1667 | - | first slice: `python -m open_fdd.ml.review`, SQL verdict always kept |
| #1692 | `grok/1635-client-run-proof` | `970c0679` | Refs #1635 | - | client half: frames carry hook-resolved run proof (needs Claude's hook half) |

| #1693 | `grok/1666-assessed-pca-greybox` | `9ee3f342` | Refs #1666 | - | PCA/gray-box `assessment()`; issue repro now 100 x missing_inputs |
| #1694 | `grok/1662-detect-help` | `509085ba` | Refs #1662 | on #1687 | detect `--method` summary, `--train-until` zone wording |
Shared-file note: `tests/test_ml_fdd.py`, `open_fdd/ml/cli.py` and `docs/python-tools.md` are touched by several
PRs at different anchors; stacks exist to avoid conflicts. Grok will rebase its own branches on request.

## Local stack-tip receipts (2026-11-17, ~6:35-6:42 PM; Windows, Python 3.14; `tests/parity` excluded, CI runs it)

| Tip | Contains | Result |
|---|---|---|
| `22974981` (#1689) | #1681 #1684 #1685 #1688 #1689 | 469 passed, 5 skipped |
| `d4dd7191` (#1686) | #1682 #1686 | 454 passed, 5 skipped |
| `d7dfd77e` (#1687) | #1678 #1687 | 452 passed, 5 skipped |
| `ab7daf55` (#1690) | #1690 | 448 passed, 5 skipped |
| `dd64c89c` (#1691) | #1691 | 454 passed, 5 skipped |
| `9ee3f342` (#1693) | #1693 | 448 passed, 5 skipped |
| `970c0679` (#1692) | #1692 | 451 passed, 5 skipped; SPARQL / run-proof parity 24 passed |
## Issue states (Grok lane)

| # | State | Notes |
|---|---|---|
| 1665 | PR READY (#1678) | acceptance 1-5 mapped to named tests |
| 1666 | PR READY partial (#1677, #1679, #1693) | still open: detect CLI/JSON exposure (after #1678) |
| 1652-1662 | PR READY (see table) | #1662 split: #1689 + #1694 |
| 1667 | PR partial (#1691) | replay, RDF inputs, labeled evaluation not done |
| 1635 | PR partial (#1692) | hook must emit `run_proof` / `run_proof_series` (Claude) |
| 1569 | not started (ontology half) | |
| 1663 | OPEN | tracker; closes only after children and 4.5.12 release evidence |
| 1669 (Claude) | INDEPENDENTLY VERIFIED on `723d90d3` | stays open until integrated and released |

## Next actions

See the latest handoff comment on the checkpoint PR.
