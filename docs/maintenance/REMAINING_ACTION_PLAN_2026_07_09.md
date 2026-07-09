# Remaining action plan — 2026-07-09

Post PR #477/#478 merge tracker.

## Completed

- [x] PR #477 merged — additive Rust/DataFusion engine on master (`3a7dafb5`)
- [x] PR #478 merged — nightly GHCR cron + smoke + frontend docs (`dfd38f51`)
- [x] Deleted `port-vibe19-rust-datafusion-engine` and `cleanup/integrate-rust-port-into-master`
- [x] `rust-ghcr.yml` — push master, cron `17 7 * * *`, workflow_dispatch
- [x] GitHub issues filed for remaining work (#479–#484)

## In progress (CI)

- [ ] Master push CI green after #478 merge
- [ ] `rust-ghcr.yml` manual dispatch run (triggered 2026-07-09)
- [ ] `rust-ghcr.yml` publish job → `openfdd-edge-rust:nightly` + `sha-*`

## GitHub issues (remaining work)

| Issue | Title | Priority |
| --- | --- | --- |
| [#479](https://github.com/bbartling/open-fdd/issues/479) | Consolidate duplicate Rust Edge CI workflows | P2 |
| [#480](https://github.com/bbartling/open-fdd/issues/480) | Review/cherry-pick stale remote branches | P2 |
| [#481](https://github.com/bbartling/open-fdd/issues/481) | React dashboard Phase B — FDD API wiring | P2 |
| [#482](https://github.com/bbartling/open-fdd/issues/482) | Expand SQL rules 19 → 50 | P3 |
| [#483](https://github.com/bbartling/open-fdd/issues/483) | Dependabot moderate vulnerabilities | P3 |
| [#484](https://github.com/bbartling/open-fdd/issues/484) | Verify rust-ghcr nightly after #478 | P1 |

## Validation checklist

```powershell
gh run list --branch master --limit 10
gh run list --workflow=rust-ghcr.yml --limit 3
cargo test -p fdd_core -p fdd_csv -p fdd_store -p fdd_sql -p fdd_rules -p fdd_bench -p fdd_cli
cd workspace/dashboard && npm ci && npm run build && npm test
```

## Do not start yet

- React FDD UI expansion until #484 verification complete
- Direct merge of stale feature branches without review (#480)
