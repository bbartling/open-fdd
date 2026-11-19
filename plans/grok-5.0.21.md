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
- Own consumer fixture (two sensors on one role, irregular cadence, 4 sweeps x PGlite/SQLite): 82/82 checks pass.
- pandas public API: `percent_0_100` gives PASS 0.0 h on base and FAULT 2.95 h here.

Open observation for Claude: in the pandas sweep, an unassessable RH unit returns PASS 0.0 rather than unassessed
(this predates #1676).

## Own tooling PRs (all into `release/5.0.21`; need a non-author review/test; Grok does not merge)

Stacked PRs keep base `release/5.0.21`; review only the top commit named in each body, except #1681 (see the
note in that row). Merge a stack bottom-up.

| PR | Branch | Head | Issue | Stack | Scope |
|---|---|---|---|---|---|
| #1677 | `grok/1666-modegated-refit` | `254ccab8` | Refs #1666 | - | ModeGated atomic refit, `assessment()` reasons, fit receipt |
| #1678 | `grok/1665-explicit-training` | `bb1dc35d` | Refs #1665 | - | `detect` needs an explicit training source; phase labels; evaluation-only counts |
| #1679 | `grok/1666-elapsed-coverage` | `6c65368d` | Refs #1666 | - | elapsed-time window eligibility, `window_coverage()`, excluded coverage |
| #1681 | `grok/1656-activity-policy` | `e8e1f898` | Refs #1656 | after #1678 | one activity policy for screen and ml detect. Head merges #1678 (`bb1dc35d`) into `b22c0f60` to resolve `open_fdd/ml/cli.py` (keeps `training_overlap`, then `activity`). Review `b22c0f60` and the merge commit. Note: https://github.com/bbartling/open-fdd/pull/1681#issuecomment-6966516861 |
| #1682 | `grok/1659-method-roles` | `60b01e87` | Refs #1659 | - | `open-fdd-ml methods`, single-zone gray-box; LBNL rerun identical (receipt on PR) |
| #1683 | `grok/1661-run-all-context` | `a73f5912` | Refs #1661 | - | explicit equipment context for run_all/run_rule, `summarize()` |
| #1684 | `grok/1654-screen-defaults` | `c37e3af7` | Refs #1654 #1658 | on #1681 @ `b22c0f60` | screen defaults run on what is installed; iforest opt-in. Still parented on the pre-merge #1681 tip; a trial merge onto `e8e1f898` was clean |
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
| #1695 | `grok/1667-labeled-eval` | `7d25142d` | Refs #1667 acc. 5 | on #1691 | `python -m open_fdd.ml.review_eval`; labeled held-out evaluation |
| #1696 | `grok/1667-review-demo` | `a6914d30` | Refs #1667 acc. 6 | on #1695 | `python -m open_fdd.ml.review_demo`; installed-wheel synthetic demo |
| #1697 | `grok/1569-extension-check` | `d313eca5` | Refs #1569 Python half | - | `open-fdd-ontology-audit --extensions`; report-only; shipped vocab not edited |
| #1698 | `grok/1666-detect-assessed` | `9342bcbf` | Refs #1666 | on #1694 + merge of #1693 | detect CLI/JSON assessed vs unassessed rows |

Suggested merge order:
1. #1674, then #1675, then #1676 (independent of the tooling PRs).
2. Standalone tooling PRs, any order: #1677, #1678, #1679, #1682, #1683, #1690, #1692, #1693, #1697.
3. **Merge #1678 before #1681.** Then #1684 -> #1685 -> #1688 -> #1689. Those four still sit on `b22c0f60`, not `e8e1f898`. A trial merge of the whole set onto `release/5.0.21` was clean after the #1681 merge. If GitHub reports a conflict, ask on the PR and Grok can add a normal merge commit (no force-push).
4. #1682 -> #1686.
5. #1678 -> #1687 -> #1694; also merge #1693; then #1698.
6. #1691 -> #1695 -> #1696.
7. #1680 last, or fold this plan into Claude's ledger and leave the checkpoint PR unmerged.

Shared-file note: `tests/test_ml_fdd.py`, `open_fdd/ml/cli.py` and `docs/python-tools.md` are touched by several PRs at different anchors. Grok will rebase or add merge commits on request (no force-push).

## Local stack-tip receipts (2026-11-17, Windows, Python 3.14; `tests/parity` excluded, CI runs it)

Earlier tips (~6:35-6:42 PM):

| Tip | Contains | Result |
|---|---|---|
| `22974981` (#1689) | #1681 #1684 #1685 #1688 #1689 | 469 passed, 5 skipped |
| `d4dd7191` (#1686) | #1682 #1686 | 454 passed, 5 skipped |
| `d7dfd77e` (#1687) | #1678 #1687 | 452 passed, 5 skipped |
| `ab7daf55` (#1690) | #1690 | 448 passed, 5 skipped |
| `dd64c89c` (#1691) | #1691 | 454 passed, 5 skipped |
| `9ee3f342` (#1693) | #1693 | 448 passed, 5 skipped |
| `970c0679` (#1692) | #1692 | 451 passed, 5 skipped; SPARQL / run-proof parity 24 passed |

Later tips (~7:20-7:50 PM):

| Tip | Contains | Result |
|---|---|---|
| `7d25142d` (#1695) | #1691 #1695 | 458 passed, 8 skipped (from the PR body) |
| `a6914d30` (#1696) | #1691 #1695 #1696 | 460 passed, 8 skipped. Installed-wheel demo exit 0 (`stuck` corroborated, `healthy_day` needs_review, `claim_supported` false). The PR body still has a FULL_SUITE_RESULT placeholder; this is the measured result. |
| `d313eca5` (#1697) | #1697 | 445 passed, 8 skipped |
| `9342bcbf` (#1698) | #1678 #1687 #1694 #1693 #1698 | 458 passed, 8 skipped |
| `e8e1f898` (#1681) | #1678 + #1681 | focused tests 62 passed, 2 skipped after the merge; earlier full suite on `b22c0f60` was 542 passed, 8 skipped |
| trial tip `e66c0cd6` (local only, not a PR) | all Grok tooling PRs merged onto `release/5.0.21` | 536 passed, 8 skipped in 1m52s |

Skip-count differences (5 vs 8) are environment extras in the venv (pyshacl / Postgres), not test failures.

## CI

No failures observed on these heads at the time of the last plan edit. Several later PRs, plus #1680, #1681, #1697 and #1698, were still queued or running in a large Actions backlog. Use the latest handoff comment on this PR for the live snapshot.

## Issue states (Grok lane)

| # | State | Notes |
|---|---|---|
| 1665 | PR READY (#1678) | acceptance 1-5 mapped to named tests |
| 1666 | PR READY (#1677, #1679, #1693, #1698) | ModeGated `assessment()` in detect should pick up via `hasattr` once #1677 merges; that combination is not tested in the #1698 stack |
| 1652-1662 | PR READY (see table) | #1662 split: #1689 + #1694 |
| 1667 | PR partial (#1691, #1695, #1696) | still open: acceptance 1 (SQL/pandas/RDF-reproduced episode), 4 (tuner before/after replay), scrubbed real-data half of 6, a real labeled corpus for 5 |
| 1635 | PR partial (#1692) | hook must emit `run_proof` / `run_proof_series` (Claude) |
| 1569 | PR partial (#1697, Python audit half) | namespace, extension TTL, SHACL shapes and vocabulary edits stay with the ontology/RDF owner. Shipped vocab audit: 29 `no_standard_parent`, 28 `no_label`, 28 `no_definition`; no terms minted in a standard namespace. Vocabulary was not changed. |
| 1663 | OPEN | tracker; closes only after children and 4.5.12 release evidence |
| 1669 (Claude) | INDEPENDENTLY VERIFIED on `723d90d3` | stays open until integrated and released |

## Next actions

See the latest handoff comment on this checkpoint PR.