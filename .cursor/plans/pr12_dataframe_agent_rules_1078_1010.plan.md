---
name: "PR-12 DataFrame API + agent rules #1078 #1010"
overview: "Migrate runtime rules/analytics to DataFusion DataFrame API and ship agent mapping/custom rules with hardcoded tuners; one program/PR train."
todos:
  - id: pr12-inventory
    content: "Inventory SQL-string rule/analytics builders in central; list cookbooks that stay SQL"
    status: pending
  - id: pr12-dataframe-core
    content: "Introduce DataFrame/logical-plan builders for registry rules; ban new SQL concat on product path"
    status: pending
  - id: pr12-migrate-batch
    content: "Migrate rules/analytics in batches with golden parity tests vs prior SQL"
    status: pending
  - id: pr12-agent-map
    content: "Agent mapping + propose/test/save custom rules API (no browser SQL catalog)"
    status: pending
  - id: pr12-tuners
    content: "Custom rules use hardcoded tuners; platform rules keep UI tuners where shipped"
    status: pending
  - id: pr12-tests
    content: "Unit + oracle dual-expression where required; update cookbooks note"
    status: pending
  - id: pr12-local-ot
    content: "Local cargo test + optional csv FDD gate 06"
    status: pending
  - id: pr12-pr-ci
    content: "Open PR (or stacked PRs if huge); muse-spark watch; merge; close #1078+#1010"
    status: pending
isProject: false
---

# PR-12 — DataFrame API + agent custom rules (#1078 + #1010)

**Parent:** [`patch_all_open_issues_master.plan.md`](patch_all_open_issues_master.plan.md)  
**Depends on:** PR-01 preferred (auth/tenant surface stable)  
**Branch:** `feat/dataframe-api-agent-rules-1078-1010`  
**Closes:** #1078, #1010  
**Models:** design=`claude-opus-5-thinking-high` · code=`composer-2.5-fast` · critique=`claude-sonnet-5-5-high` · CI watch=`muse-spark-1.3-high`

## Goal

Product/runtime prefers typed DataFusion DataFrame builders; SQL remains in docs/cookbooks (+ pandas twin) only. Agents can map points→roles and save custom rules with **hardcoded tuners** — no browser SQL catalog UI.

## SQL-string density (migrate in this order)

| Area | Approx `SELECT` sites | Notes |
| --- | --- | --- |
| `services/central/src/analytics/historian.rs` | ~39 | **Sole owner of this file** in the merge train |
| `crates/fdd_rules/src/runner.rs` | ~9 | |
| `crates/fdd_sql/src/session.rs` | ~6 | |
| `edge/src/fdd/registry_api.rs` | ~6 | |
| `crates/fdd_sql/src/historian.rs` | ~5 | |
| other fdd_sql / occupancy | fewer | |

## Stacked PRs if XL

1. **I1** — builders + CI lint ban + `fdd_rules/runner.rs`  
2. **I2** — `analytics/historian.rs` migration  
3. **I3** — #1010 agent custom-rule path (MCP; closes #1010)

Do not close either issue on compile-only — Pandas-oracle ↔ DataFrame parity on identical fixtures is mandatory. Gate `40_no_id_heuristics.sh` must stay green.  

Still one program; master track E owns all three until both issues close.

## Local verify

```bash
cargo test -p openfdd-central -- rules
cargo test -p openfdd-central -- analytics
# optional:
./scripts/nightly-ot-bench/06_csv_fdd_sql.sh
```

## Non-goals

- Do not rewrite DataFusion
- Do not remove cookbook SQL
- Do not hardcode buildings/equipment ids
