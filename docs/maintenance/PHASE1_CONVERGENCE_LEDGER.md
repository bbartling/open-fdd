# Phase 1 Convergence Ledger

**Audit timestamp:** 2026-07-13T13:00:00Z (WSL)
**Repo:** `bbartling/open-fdd`
**Local path:** `/home/ben/open-fdd`

## Snapshot

| Item | Value |
| --- | --- |
| `origin/master` SHA | `defba063` (Merge PR #491) |
| PR #493 head SHA | `c68210bd` (pre-this-iteration; update on push) |
| Open PRs | **#493** only |
| Open issues | **#481**, **#482**, **#483** |
| Remote branches | `master`, `docs/pid-hunt-1-and-operational-gates` |
| Local-only branches | none |
| Worktrees | single (`/home/ben/open-fdd`) |
| Stashes | empty |
| VERSION file | `3.3.0-beta.1` |
| edge Cargo version | `3.2.13` (drift — release decision pending) |
| Latest release | `v3.2.8` |
| PR ↔ master | 6 commits ahead, 0 behind |

## Registry inventory (source-derived)

| Slice | Count |
| --- | ---: |
| Registry rules (`sql_rules/registry.yaml`) | **55** |
| SQL files on disk | **55** |
| Unique `rule_id` | **55** |
| Orphan SQL files | **0** |
| PID-HUNT-1 | 1 (additive) |
| Analytics rollups (FAN-RUNTIME-HOURS, ZONE-COMFORT-PCT, AVG-ZONE-TEMP, FAULT-ELAPSED-HOURS) | 4 |
| Canonical OG50 FDD rules | 50 |
| `parity_status: proven_building_100` | ~18 (historical 19-rule benchmark era) |
| `parity_status: cookbook_defined` | remainder |

## Workflows (PR #493 head `c68210bd`)

All required PR checks **SUCCESS** on latest push:

- Rust Edge CI (fmt/clippy/tests, TS build, Docker, Compose API smoke)
- FDD DataFusion Engine CI
- Cookbook parity
- AppSec (audit, Gitleaks, Trivy, Hadolint, npm audit)
- Rust Edge Security Guards
- Docs (GitHub Pages)

Nightly GHCR publish on `master`: run `29243276953` **success** (2026-07-13).

**Docker CLI unavailable in this WSL environment** — GHCR digests must be verified via `gh` API / host Docker Desktop.

## Vibe19 oracle

| Item | Value |
| --- | --- |
| Path | `/mnt/c/Users/ben/Documents/py-bacnet-stacks-playground/vibe_code_apps_19` |
| SHA | `5006a16f2c7729145e9765e719f72d816489f5ee` |
| Small golden | **pending** (system Python lacks pandas; venv install in progress) |
| Golden CSVs | `motor_hours`, `motor_weekly`, `mech_cooling_oat_bins`, `rcx_preset_coverage`, `rcx_preset_digests`, `rule_digest`, `fingerprints.json` |

## Building 100

| Item | Value |
| --- | --- |
| Path | `/mnt/c/Users/ben/OneDrive/Desktop/testing/tadco_openfdd_sidecar/workspace/imports/hvac_systems_CLEANED` |
| Shape | `BUILDING_100/` tree + `BUILDING_100.zip` + weather |
| Open-FDD validate | **PASS** (prior session) |
| Full 55-rule parity | **NOT RUN** this session |
| Private data committed? | **No** |

## Dependabot / #483

| Alert | Package | Severity | Fixed version |
| --- | --- | --- | --- |
| #32 / #29 | `thrift` `<= 0.22.0` | moderate | **null** (no upstream patch published in alert) |

Reachability: transitive (Parquet/Arrow stack). Cannot close #483 until a patched transitive graph exists or risk is formally accepted with evidence.

## Review threads (PR #493)

| State | Count |
| --- | ---: |
| Total threads | 21 |
| Unresolved (start of this iteration) | **2** |
| Prior SQL threads | resolved in `c68210bd` |

Unresolved at start:

1. `registry_api.rs` — do not publish defaults as `effective` when tuning load fails
2. `SqlFddRulesPage.tsx` — preserve canonical `rule_id` (no slugify)

## Capability matrix

| Capability | Vibe19 behavior | Open-FDD current state | Test evidence | Gap | Task |
| --- | --- | --- | --- | --- | --- |
| CSV upload | Sidebar folder/zip | `/csv-workbench` routed | page + API exist | ZIP package incomplete | #481 |
| Multiple CSV | supported | preview API multi-file | unit/integration partial | UX polish | #481 |
| ZIP import | package_io | partial CSV ingest | — | full package parity | #481 |
| Preview | package health | CSV preview cards | — | schema warnings | #481 |
| JSON mapping | column_map.json | multiple stores | — | versioned unified store | #481 |
| Arrow persistence | pandas/feather | Feather/Parquet ingest | fdd_store | — | keep |
| Rule registry | cookbook 53 | **55** SQL registry + `/api/fdd/rules` | edge unit test | — | done API |
| Operational gating | runtime | SQL + runner roles | docs + partial runtime | OFF/N/A statuses incomplete | engine |
| Six-status result model | PASS/FAULT/skips | improving in runner | unit tests | full six-status | engine |
| Golden analytics | pytest goldens | no Open-FDD harness yet | Vibe19 pending | parity CLI | harness |
| Building 100 parity | optional digest | validate only; doc @ 19 rules | historical MD | 55-rule re-run | #482 |
| Plotly charts | FDD/RCx plots | PlotPage exists | — | fault timelines etc. | #481 |
| Reports | DOCX/CSV | ReportBuilder | — | run manifests | #481 |
| GHCR release | n/a | nightly on master | Actions success | WSL can't smoke-pull | post-merge |

## Next highest-risk task

1. Fix remaining CodeRabbit findings + registry render integrity tests.
2. Run Vibe19 small golden (venv).
3. BUILDING_100 `fdd_cli` 55-rule run + honest #482 status.
4. Do **not** close #481/#482/#483 until acceptance evidence exists.

## Issue closure policy (this PR)

| Issue | Keyword | Gate |
| --- | --- | --- |
| #482 | `Refs #482` until B100+executable proof | SQL files alone insufficient |
| #481 | `Refs #481` until full workbench | route ≠ done |
| #483 | open until thrift patched or accepted | no fake close |
