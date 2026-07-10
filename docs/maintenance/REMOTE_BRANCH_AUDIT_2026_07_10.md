# Remote Branch Audit — 2026-07-10

Issue: [#480](https://github.com/bbartling/open-fdd/issues/480)

Method:

- `git fetch --all --prune`
- `git log --oneline origin/master..origin/<branch>`
- `git cherry origin/master origin/<branch>` (`+` = patch not in master by patch-id)
- `git diff origin/master...<branch>` (three-dot since diverge — misleading after squash)
- Tip-to-tip file compare for candidates with `cherry+ > 0`
- `gh pr list --state all --head <branch>`

**Do not delete until classification is recorded and unique commits are recovered or explicitly declined.**

## Summary table

| Branch | PR | ahead | cherry+ | Classification | Notes |
| --- | --- | --- | --- | --- | --- |
| `fix/rust-ghcr-smoke-isolated-workspace` | #489 MERGED | 0 | 0 | **MERGED_DELETE** | Safe |
| `fix/rust-ghcr-docker-smoke-auth` | #487 MERGED | 0 | 0 | **MERGED_DELETE** | Safe |
| `docs/remaining-action-plan-issues` | #485 MERGED | 0 | 0 | **MERGED_DELETE** | Safe |
| `fix/nightly-ghcr-and-react-cutover` | #478 MERGED | 0 | 0 | **MERGED_DELETE** | Safe |
| `docs/edge-tester-gh-actions-watch-prompt` | #454 MERGED | 1 | 0 | **MERGED_DELETE** | Patch equivalent on master |
| `fix/bacnet-server-runtime-poll-persist` | #451 MERGED | 2 | 0 | **MERGED_DELETE** | Patch equivalent on master |
| `docs/cookbook-phase-2a-2b` | #450 MERGED | 1 | 0 | **MERGED_DELETE** | Patch equivalent |
| `docs/cookbook-v2-public-fdd` | #449 MERGED | 1 | 0 | **MERGED_DELETE** | Patch equivalent |
| `docs/edge-tester-issue-orchestration` | #448 MERGED | 1 | 0 | **MERGED_DELETE** | Patch equivalent |
| `docs/vibe16-product-agent-charter` | #447 MERGED | 1 | 0 | **MERGED_DELETE** | Patch equivalent |
| `feat/bench-330-scripts-and-agent-prompt` | #443 MERGED | 1 | 0 | **MERGED_DELETE** | Patch equivalent |
| `feat/release-channels-nightly-beta-stable` | #442 MERGED | 1 | 0 | **MERGED_DELETE** | Patch equivalent |
| `fix/audit-allowlist-bench-docs` | #441 MERGED | 1 | 0 | **MERGED_DELETE** | Patch equivalent |
| `docs/rule-cookbook-datafusion-pandas` | #446 MERGED | 2 | 2 | **SUPERSEDED_DELETE** | Squash/rebase; cookbook files present on master (1219+ lines) |
| `fix/docs-pages-github-actions-only` | #440 MERGED | 4 | 4 | **SUPERSEDED_DELETE** | Squash; `docs/operations/github-pages.md` on master |
| `fix/bacnet-whois-shell-5007` | #445 MERGED | 4 | 4 | **SUPERSEDED_DELETE** | Merged then superseded by later BACnet P0s (#451/#459/#475). Tip differs from master because master advanced. |
| `chore/product-gh-actions-deep-sleep` | none | 2 | 1 | **CHERRY_PICK_FIRST** | Incremental agent prompt/script improvements vs master copies of same paths |

## CHERRY_PICK_FIRST detail

### `chore/product-gh-actions-deep-sleep`

Unique tip commit: `49b89a64` — *Add product GH Actions deep-sleep watch and edge GHCR-only constraint.*

Files that still differ from master tip:

- `docs/agent/linux-edge-tester-gh-actions-watch-prompt.md` — GHCR-only / no local build bench constraint
- `docs/agent/wsl-product-gh-actions-deep-sleep-prompt.md` — expanded deep-sleep paste prompt
- `scripts/openfdd_product_gh_actions_watch.sh` — richer wake payload / commit message in status

**Recommendation:** cherry-pick or manually port these three file updates in a small docs PR after Phase 1, then delete the branch. Do not restore unrelated historical tip state (branch tip is far behind master on FDD crates).

## Local branches (not on remote or gone)

| Local | Remote | Action |
| --- | --- | --- |
| `cleanup/integrate-rust-port-into-master` | gone | Local cleanup after #477; delete local when convenient |
| `port-vibe19-rust-datafusion-engine` | gone | **Do not restore** (hard rule) |
| `fix/rust-ghcr-*`, `docs/remaining-*`, `fix/nightly-*` | still remote | Delete with remotes after Phase 4 execute |

## Deletion batch (safe now after this audit — execute in Phase 4 closeout)

```text
fix/rust-ghcr-smoke-isolated-workspace
fix/rust-ghcr-docker-smoke-auth
docs/remaining-action-plan-issues
fix/nightly-ghcr-and-react-cutover
docs/edge-tester-gh-actions-watch-prompt
fix/bacnet-server-runtime-poll-persist
docs/cookbook-phase-2a-2b
docs/cookbook-v2-public-fdd
docs/edge-tester-issue-orchestration
docs/vibe16-product-agent-charter
feat/bench-330-scripts-and-agent-prompt
feat/release-channels-nightly-beta-stable
fix/audit-allowlist-bench-docs
docs/rule-cookbook-datafusion-pandas
fix/docs-pages-github-actions-only
fix/bacnet-whois-shell-5007
```

Hold until cherry-pick:

```text
chore/product-gh-actions-deep-sleep
```

## Counts

| Metric | Value |
| --- | --- |
| Remote non-master branches audited | 17 |
| MERGED_DELETE | 13 |
| SUPERSEDED_DELETE | 3 |
| CHERRY_PICK_FIRST | 1 |
| KEEP_ACTIVE | 0 |
| INVESTIGATE remaining | 0 (after this pass) |

## Status

- Audit document: **written**
- Remote deletes: **not yet executed** (wait for Phase 1 merge + cherry-pick of deep-sleep deltas)
- Issue #480: update with this table; close only after deletes + cherry-pick decision complete
