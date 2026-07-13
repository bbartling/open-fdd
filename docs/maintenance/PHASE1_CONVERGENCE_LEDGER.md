# Phase 1 Convergence Ledger

**Audit timestamp:** 2026-07-13T15:20:00Z (WSL)
**Repo:** `bbartling/open-fdd`
**Local path:** `/home/ben/open-fdd`

## Snapshot

| Item | Value |
| --- | --- |
| `origin/master` SHA | `defba063` |
| PR #493 head SHA | `78c5c590`+ (analytics rollups commit pending) |
| Open PRs | **#493** only |
| Open issues | **#481**, **#482**, **#483** |
| Remote branches | `master`, `docs/pid-hunt-1-and-operational-gates` |
| Worktrees | single (`/home/ben/open-fdd`) |
| Stashes | empty |
| VERSION file | `3.3.0-beta.1` |
| Latest release | `v3.2.8` |
| PR ↔ master | ~22 commits ahead, 0 behind |
| Unresolved CodeRabbit threads | **0** (after `78c5c590` replies) |

## Registry inventory

| Slice | Count |
| --- | ---: |
| Registry rules | **55** |
| OG50 | **50** |
| PID-HUNT-1 | 1 |
| Analytics rollups (registry slots) | 4 |

## Proven this cycle

- Six-status contract + RUN gate SQL injection + review hardening (`78c5c590`)
- PR description rewritten (Proven / Remaining) via REST; issue comments on #481/#482/#483
- `motor_hours` / `motor_weekly` / `mech_cooling_oat_bins` Rust rollups match Vibe19 small golden
- Weather ingest: building-local weather path + `wx_oa_t` → `oa_t`; sibling `*_weather` parquet keeps history schema clean
- Mapping equivalence doc: `docs/benchmarks/BUILDING_100_MAPPING_EQUIVALENCE.md`
- ZIP package tests (10); dashboard vitest (73); `fdd_rules` lib (33)

## Building 100

| Item | Value |
| --- | --- |
| Open-FDD 55-rule run | PASS (0 ERROR) — `BUILDING_100_55RULE_RUN_2026_07_13.md` |
| Parity summary | `pass: false` — SV-STALE plant/VAV classified as mapping mismatch; FC residual within investigation |
| Private data committed? | **No** |

## Remaining merge gate

1. B100 comparable numeric parity after mapping hygiene (no unexplained mismatches)
2. RCx / rule_digest rollup golden wiring
3. Workbench run-manifest/export polish + Plotly portfolio heatmap if still open
4. #483 Dependabot disposition against thrift waiver
5. Green current HEAD after this push; then merge → `3.3.0-beta.2` → GHCR verify → prune branch

## Vibe19

| Item | Value |
| --- | --- |
| Path | `/mnt/c/Users/ben/Documents/py-bacnet-stacks-playground/vibe_code_apps_19` |
| SHA | `5006a16f` |
| Small golden | PASS |
