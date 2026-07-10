# Open-FDD unstuck status — 2026-07-09

**Updated:** after PR #487 merge; follow-up PR for isolated smoke workspace pending.

## Repository state

| Item | Value |
| --- | --- |
| Local branch | `fix/rust-ghcr-smoke-isolated-workspace` |
| Master | `d6ec5fc2` — Merge PR #487 |
| Open PRs | none (487 merged; follow-up branch opening) |

## Merged PRs (confirmed)

| PR | Title | Status |
| --- | --- | --- |
| #477 | Additive Vibe19 Rust/DataFusion engine | merged |
| #478 | Nightly GHCR cron + frontend docs | merged |
| #485 | Remaining action plan docs | merged |
| #487 | rust-ghcr Docker smoke auth/workspace | merged (partial fix) |

## PR #487 gap

Merged workflow sets `-e OFDD_AUTH_REQUIRED=false` but mounts repo `workspace/` after compose step writes `workspace/auth.env.local` with `OFDD_AUTH_REQUIRED=true`. Edge `apply_env_file()` **overrides** docker `-e` for `OFDD_*` keys.

**Follow-up:** Option B — isolated `$RUNNER_TEMP/openfdd-smoke-workspace` (no auth file).

## `rust-ghcr.yml` on master (post #487)

| Feature | Present |
| --- | --- |
| `schedule: cron "17 7 * * *"` | yes |
| `concurrency: rust-ghcr-nightly` | yes |
| FDD crate tests in test job | yes |
| Docker smoke step | yes (needs isolated workspace) |
| test job `timeout-minutes: 60` | **follow-up PR** |
| publish `timeout-minutes: 300` | yes |

## FDD engine location (Phase 1)

| Crate | Package | Path |
| --- | --- | --- |
| fdd_core | fdd_core | crates/fdd_core |
| fdd_csv | fdd_csv | crates/fdd_csv |
| fdd_store | fdd_store | crates/fdd_store |
| fdd_sql | fdd_sql | crates/fdd_sql |
| fdd_rules | fdd_rules | crates/fdd_rules |
| fdd_bench | fdd_bench | crates/fdd_bench |
| fdd_cli | fdd_cli (bin: openfdd_cli) | crates/fdd_cli |

Also: `sql_rules/`, `rule_tuning/`, `tools/python_oracle/` (oracle only).

**Local FDD tests:** pass (all 7 crates).

## Workflow runs

| Run | Status | Notes |
| --- | --- | --- |
| 29058174607 | in_progress | manual dispatch post #487 |
| 29053499719 | failure | auth smoke (pre #487) |
| 29050366982, 29043288854 | cancelled | superseded by concurrency |

## Open issues

| Issue | Title |
| --- | --- |
| #479 | Duplicate CI workflows |
| #480 | Stale remote branches |
| #481 | React Phase B API wiring |
| #482 | SQL rules 19→50 |
| #483 | Dependabot |
| #484 | Verify rust-ghcr nightly (open until green publish) |
| #486 | Stuck rust-ghcr runs |
| #488 | Flaky RDF parallel test |

## Local validation

| Check | Result |
| --- | --- |
| FDD crate tests | pass |
| Dashboard build/test | pending this session |
| Docker smoke | pending (Docker Desktop may be offline) |

## React Phase B (#481)

**Not ready** until rust-ghcr smoke + publish green on master (#484).

## Next branch/PR

`fix/rust-ghcr-smoke-isolated-workspace` → merge → manual `gh workflow run rust-ghcr.yml` → close #484/#486 if green.
