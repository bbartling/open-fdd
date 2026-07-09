# Branch cleanup after PR #477 merge

**Date:** 2026-07-09  
**Master after merge:** `3a7dafb5` (PR #477)

## Deleted (safe)

| Branch | Reason |
| --- | --- |
| `cleanup/integrate-rust-port-into-master` | Fully merged via PR #477 |
| `port-vibe19-rust-datafusion-engine` | Destructive port (83k deletions); engine work integrated additively on master |

## Kept — investigate / cherry-pick later

| Branch | Unique commits | Classification |
| --- | --- | --- |
| `feat/release-channels-nightly-beta-stable` | 1 | **investigate** — release channel docs + GHCR tweaks; partial overlap with `fix/nightly-ghcr-and-react-cutover` |
| `fix/bacnet-whois-shell-5007` | 4 | **investigate** — Who-Is fixes + agent docs; may overlap with #475 on master |
| `fix/bacnet-server-runtime-poll-persist` | 2 | **investigate** — BACnet runtime poll |
| `fix/docs-pages-github-actions-only` | 4 | **investigate** — docs-pages workflow |
| `fix/audit-allowlist-bench-docs` | 1 | **cherry-pick first** — audit allowlist |
| `chore/product-gh-actions-deep-sleep` | 2 | **keep** — GH Actions watch scripts/docs |
| `docs/cookbook-phase-2a-2b` | 1 | **superseded by newer docs** — prompt branch |
| `docs/cookbook-v2-public-fdd` | 1 | **superseded by newer docs** |
| `docs/rule-cookbook-datafusion-pandas` | 2 | **superseded by #477 docs** |
| `docs/edge-tester-gh-actions-watch-prompt` | 1 | **superseded** — agent prompt |
| `docs/edge-tester-issue-orchestration` | 1 | **superseded** |
| `docs/vibe16-product-agent-charter` | 1 | **keep** — product charter |
| `feat/bench-330-scripts-and-agent-prompt` | 1 | **keep** — bench scripts |

## Already merged / deleted earlier (2026-07-09)

- `docs/go-nuts-prompt-33213` — merged #476
- `docs/edge-go-nuts-prompt-3312`, `docs/edge-retest-prompt-3312`, `docs/edge-retest-prompt-3311`
- `fix/bench-closeout-33212`, `fix/ghcr-timeout-and-edge-prompt`, `docs/cookbook-economizer-guide`

## Local stale branches

| Branch | Action |
| --- | --- |
| `dev` | delete local (remote gone) |
| `rust-rewrite-1` | delete local (remote gone) |
