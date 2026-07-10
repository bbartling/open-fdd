# Open-FDD Project Recovery Register — 2026-07-10

Verified locally and via GitHub CLI. Do not treat prior chat summaries as source of truth without re-checking this file.

## Snapshot

| Field | Value |
| --- | --- |
| Current branch | `master` |
| Current commit | `52a7d2c09ba714be22b7f4774edf957299da9b43` |
| Dirty/clean | **clean** |
| Default branch | `master` |
| Open PR count | **0** |
| Open issue count | **7** |
| Working tree | up to date with `origin/master` |

## Open issues

| # | Title |
| --- | --- |
| 479 | Consolidate duplicate Rust Edge CI workflows (ci.yml vs rust-ci.yml) |
| 480 | Review and cherry-pick stale remote branches post PR #477 |
| 481 | React dashboard Phase B: wire FDD registry/tuning/run APIs |
| 482 | Expand SQL rule registry from 19 to 50 rules (parity with cookbook) |
| 483 | Address Dependabot moderate vulnerabilities on default branch |
| 486 | Stuck in_progress rust-ghcr workflow runs on master (concurrency?) |
| 488 | Flaky edge test: list_points_filters_by_csv_import_site (parallel CI) |

## Recent merged PRs (recovery-relevant)

| PR | Title | Notes |
| --- | --- | --- |
| #489 | isolate rust-ghcr Docker smoke workspace | Merged; HEAD of master |
| #487 | rust-ghcr Docker smoke auth/workspace | Merged |
| #485 | remaining action plan issues | Docs + issue tracker |
| #478 | nightly GHCR and React cutover | Workflow + docs |
| #477 | integrate rust port into master | FDD crates landed |

## Recent workflows

### Failed (blocking)

| Run | Workflow | Event | Failure |
| --- | --- | --- | --- |
| [29086512922](https://github.com/bbartling/open-fdd/actions/runs/29086512922) | Publish Rust edge to GHCR | `schedule` | `docker/metadata-action@v5`: `Cannot read properties of undefined (reading 'hash')` after test green |
| [29060210628](https://github.com/bbartling/open-fdd/actions/runs/29060210628) | Publish Rust edge to GHCR | `workflow_dispatch` | Same metadata-action crash |
| [29058174607](https://github.com/bbartling/open-fdd/actions/runs/29058174607) | Publish Rust edge to GHCR | `workflow_dispatch` | Same class of publish failure |

**Root cause (confirmed from logs):** publish job uses

```yaml
type=raw,value=nightly-{{date format='YYYYMMDD' timezone='UTC'}}
```

Handlebars helper expects positional format + `tz=` hash (`{{date 'YYYYMMDD' tz='UTC'}}`). Named `format=` / `timezone=` leaves `options` undefined → `.hash` TypeError. Affects schedule and workflow_dispatch (and any event that evaluates that raw tag).

### Successful (recent)

| Run | Workflow | Notes |
| --- | --- | --- |
| 29060193360 | Rust Edge CI | Success on #489 merge |
| 29060193413 | Publish Open-FDD MCP to GHCR | Success |
| 29058871945 / 29058871986 | Rust Edge CI (PR #489) | Success |
| 28907372364 | Publish Rust edge to GHCR | Last successful edge publish (2026-07-08 push) |

### Cancelled (concurrency)

Multiple `rust-ghcr` push runs cancelled by `concurrency.group: rust-ghcr-nightly` + `cancel-in-progress: true` when a newer run starts. No currently `in_progress` stuck runs observed in the latest 30 `rust-ghcr` listings (all `completed`).

## Remote branches (non-master)

| Branch | Classification hint (pending Phase 4 audit) |
| --- | --- |
| `origin/fix/rust-ghcr-smoke-isolated-workspace` | MERGED (#489) — delete candidate |
| `origin/fix/rust-ghcr-docker-smoke-auth` | MERGED (#487) — delete candidate |
| `origin/fix/nightly-ghcr-and-react-cutover` | MERGED (#478) — delete candidate |
| `origin/docs/remaining-action-plan-issues` | MERGED (#485) — delete candidate |
| `origin/chore/product-gh-actions-deep-sleep` | Inspect |
| `origin/docs/edge-tester-gh-actions-watch-prompt` | Likely superseded |
| `origin/docs/cookbook-phase-2a-2b` | Likely merged |
| `origin/docs/cookbook-v2-public-fdd` | Likely merged |
| `origin/docs/edge-tester-issue-orchestration` | Likely merged |
| `origin/docs/rule-cookbook-datafusion-pandas` | Likely merged |
| `origin/docs/vibe16-product-agent-charter` | Likely merged |
| `origin/feat/bench-330-scripts-and-agent-prompt` | Likely merged |
| `origin/feat/release-channels-nightly-beta-stable` | Likely merged |
| `origin/fix/audit-allowlist-bench-docs` | Likely merged |
| `origin/fix/bacnet-server-runtime-poll-persist` | Inspect unique commits |
| `origin/fix/bacnet-whois-shell-5007` | Inspect unique commits |
| `origin/fix/docs-pages-github-actions-only` | Likely merged |

Local-only / gone remotes: `cleanup/integrate-rust-port-into-master` (gone), `port-vibe19-rust-datafusion-engine` (gone — do not restore).

## GHCR published tags

`docker buildx imagetools inspect ghcr.io/bbartling/openfdd-edge-rust:nightly` **succeeds** (stale successful publish still present):

- Digest: `sha256:3f60ca25f7b1afba297e5c5bb0648e4d4f375bcf23538f91c19f6ef878b32346`
- Platforms: `linux/amd64`, `linux/arm64`
- Package API listing: **403** (token lacks `read:packages`); inspect via Docker works.

Nightly is **stale relative to master** — publish has failed since smoke fixes landed on `52a7d2c`.

## Rust workspace

Members (`Cargo.toml`):

- `edge`
- `mcp`
- `crates/fdd_core`
- `crates/fdd_csv`
- `crates/fdd_store`
- `crates/fdd_sql`
- `crates/fdd_rules`
- `crates/fdd_bench`
- `crates/fdd_cli`

## Edge package dependencies on `fdd_*`

**None.** `edge/Cargo.toml` does not path-depend on any `fdd_*` crate. Edge still uses in-tree `edge/src/fdd` (rules, DataFusion SQL, wires, etc.). New crates are workspace members and tested in `rust-ghcr` / FDD CI, but **not integrated into the production edge HTTP API**.

## React / frontend

| Path | Role |
| --- | --- |
| `workspace/dashboard` | React/TypeScript/Vite source |
| `frontend` | Compiled production assets served by edge |

## Dockerfile stages

1. **dashboard** — `node:22-bookworm`, `npm ci` + `npm run build` → `/app/frontend`
2. **builder** — `rust:1.95-bookworm`, copies `Cargo.toml`/`Cargo.lock`, `edge/`, `mcp/`, `crates/`, release-builds edge + mcp
3. **runtime** — `debian:bookworm-slim`, non-root `openfdd`, binaries + frontend

**Not copied into runtime today:** `sql_rules/`, `rule_tuning/`.

## SQL registry

| Metric | Count |
| --- | --- |
| `rule_id` entries in `sql_rules/registry.yaml` | **19** |
| `sql_rules/*.sql` files | **19** |
| Target (issue #482) | **50** |

## Python oracle

Present under `tools/python_oracle/` (`export_pandas_oracle.py`, `validate_data.py`, `debug_rule_parity.py`, README). Allowed as oracle/test tooling only — not a production path.

## BUILDING_100

- Local cache path exists: `.cache/parquet/building=BUILDING_100` (must not be committed)
- Docs: `docs/BUILDING_100_BENCHMARK.md`
- CI must use synthetic fixtures only

## Workflow inventory

Active under `.github/workflows/`:

- `ci.yml`, `rust-ci.yml`, `fdd-engine-ci.yml` — duplicate/overlapping Rust gates (#479)
- `rust-ghcr.yml` — edge nightly publish (**broken on metadata**)
- `rust-ghcr-mcp.yml`, `ghcr-prune.yml`, `ghcr-multiarch-publish.yml`
- `docker-publish.yml`, `docker-supervisor-check.yml`, `publish-open-fdd.yml`
- `rust-release.yml`, `security.yml`, `appsec.yml`
- `docs-pages.yml`, `docs-pdf.yml`, `cookbook-parity.yml`

## Blockers (severity order)

1. **P0 — GHCR publish broken** on schedule + workflow_dispatch (metadata-action Handlebars). Blocks fresh multi-arch nightly for current master.
2. **P1 — Duplicate CI** (`ci.yml` vs `rust-ci.yml`) wastes runners and confuses green/red (#479).
3. **P1 — Flaky RDF test** under parallel cargo test (#488).
4. **P1 — Stale remote branches** need audit/delete (#480).
5. **P2 — Edge does not depend on `fdd_*` crates**; API/dashboard Phase B incomplete (#481).
6. **P2 — SQL registry at 19/50** (#482).
7. **P2 — Runtime image lacks `sql_rules` / `rule_tuning`**.
8. **P3 — Dependabot moderate alerts** (#483).
9. **P3 — Node 20 deprecation warnings** on Actions (action major bumps).
10. **P3 — #486 stuck runs**: latest listing shows completed failures/cancels, not live stuck jobs; still needs concurrency/timeout documentation and closure evidence.

## Architecture confirmation

- Production: one Rust edge image, one API origin, compiled React dashboard in-image.
- No separate frontend container by default.
- No reintroduction of old Python FastAPI app.
- Vibe Code App 19 remains external oracle/demo only.
