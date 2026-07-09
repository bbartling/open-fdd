# Open-FDD branch and PR cleanup — 2026-07-09

## Safety checkpoint (Step 0)

| Item | Value |
| --- | --- |
| Starting branch | `port-vibe19-rust-datafusion-engine` @ `a3af3ac9` |
| Working tree | **Clean** — no safety commit needed |
| Default branch | `master` @ `f8452665` (after PR #476 merge) |

## Branch inventory (Step 1)

### Local branches

| Branch | Tracking | Notes |
| --- | --- | --- |
| `master` | `origin/master` | Production default |
| `port-vibe19-rust-datafusion-engine` | origin | Vibe19 Rust port (gutted edge) |
| `cleanup/integrate-rust-port-into-master` | new | **Integration branch** — additive port |
| `dev` | origin gone | Stale local |
| `rust-rewrite-1` | origin gone | Stale local |

### Remote branches (22)

| Branch | Classification | Action |
| --- | --- | --- |
| `master` | default | keep |
| `port-vibe19-rust-datafusion-engine` | unique engine work | **INTEGRATED** via cleanup branch; delete after PR merge |
| `docs/go-nuts-prompt-33213` | stale prompt | **MERGED** #476 → delete remote |
| `docs/edge-go-nuts-prompt-3312` | stale prompt | **MERGED** #474 → delete remote |
| `docs/edge-retest-prompt-3312` | stale prompt | **MERGED** #473 → delete remote |
| `docs/edge-retest-prompt-3311` | stale prompt | **CLOSED** #463 → delete remote |
| `fix/bench-closeout-33212` | edge fix | **MERGED** #472 → delete remote |
| `fix/ghcr-timeout-and-edge-prompt` | CI + prompt | superseded by later merges → delete remote |
| `docs/cookbook-economizer-guide` | docs | **MERGED** #462 → delete remote |
| `chore/product-gh-actions-deep-sleep` | CI docs | not merged; **KEEP_FOR_NOW** (low risk) |
| `docs/cookbook-phase-2a-2b` | docs | merged #450 → delete if exists |
| `docs/cookbook-v2-public-fdd` | docs | merged #449 → delete if exists |
| `docs/rule-cookbook-datafusion-pandas` | docs | merged → delete if exists |
| `docs/edge-tester-*` | prompts | merged → delete if exists |
| `fix/bacnet-*` | edge fixes | merged via PRs → delete if exists |
| `feat/*` | features | merged → delete if exists |

## Open PRs (Step 2)

| Before | After |
| --- | --- |
| **1 open** (#476) | **0 open** |

### PR #476 — `docs/go-nuts-prompt-33213`

| Field | Value |
| --- | --- |
| Title | go-nuts tester prompt → 3.2.13 @ 10c5aa5 |
| Files | 1 doc file |
| Conflicts | None |
| Decision | **MERGED** 2026-07-09 |
| Branch deleted | yes (via gh pr merge) |

## Port branch decision (Step 4)

**Do NOT merge `port-vibe19-rust-datafusion-engine` directly into `master`.**

That branch **gutted** the production Open-FDD edge product (`edge/`, `workspace/`, Docker stacks — ~83k lines removed).

### Integration strategy (chosen)

Branch: `cleanup/integrate-rust-port-into-master`

**Additive import from port branch:**

- `crates/fdd_*` (7 crates)
- `sql_rules/` (19 rules + registry)
- `rule_tuning/`
- `tools/python_oracle/`
- `examples/sample_data/BUILDING_FIXTURE/`
- Port docs (`docs/PORT_*`, `docs/RUST_DATAFUSION_ENGINE.md`, migration specs, benchmark)

**Preserved from master:**

- `edge/` + `mcp/` workspace (v3.2.13)
- `workspace/dashboard/`, Docker, frontend
- Existing `.github/workflows/` (edge CI, GHCR, docs)
- Agent docs under `docs/agent/`

**Workspace merge:**

- Root `Cargo.toml` now includes `edge`, `mcp`, and all `crates/fdd_*` members
- New workflow: `.github/workflows/fdd-engine-ci.yml` (FDD-only CI path)

## Tests (Step 6)

| Command | Result |
| --- | --- |
| `cargo fmt --all` | pass |
| `cargo test -p fdd_*` (all 7 crates) | **pass** (23 tests) |
| `cargo test -p open_fdd_edge_prototype` | **blocked locally** — Windows `libclang` missing (oxigraph bindgen); CI Linux unaffected |
| `cargo clippy --workspace` | not run full (edge env blocker); fdd clippy in CI workflow |

## Count reconciliation (50-rule prep)

Canonical pandas cookbook = **50 rules** (see Vibe19 `cookbook_rules.py`).  
Current SQL registry = **19 rules** implemented.  
50-rule expansion is **next phase** after this PR merges to `master`.

## Next steps

1. Merge PR `cleanup/integrate-rust-port-into-master` → `master`
2. Delete `origin/port-vibe19-rust-datafusion-engine` after integration verified
3. Delete stale prompt/doc remote branches listed above
4. Start 50-rule SQL registry expansion on fresh branch from `master`

## Safe to start 50-rule task?

**After integration PR merges:** yes — repo will have edge product + FDD engine coexisting on `master`.
