# DataFrame migration inventory (#1078 / PR-12 I1)

Generated: 2026-10-03T18:25Z

Sacred cookbooks stay SQL for humans/agents. Product runtime migrates off string concat.

| File | `SELECT ` count | Notes |
| --- | ---: | --- |
| `services/central/src/analytics/historian.rs` | 39 | |
| `crates/fdd_rules/src/runner.rs` | 9 | |
| `crates/fdd_sql/src/session.rs` | 6 | |
| `crates/fdd_sql/src/historian.rs` | 5 | |
| `edge/src/fdd/registry_api.rs` | 6 | |
| `crates/fdd_rules/src/occupancy_schedule.rs` | 4 | |
| `services/central/src/live_historian.rs` | 1 | |

## format! SQL concat sites

```
services/central/src/live_historian.rs:1251:            .sql(&format!("SELECT history.*, {nulls} FROM history"))
crates/fdd_rules/src/occupancy_schedule.rs:145:        format!("SELECT *, CAST({expr} AS VARCHAR) AS occ_mode FROM history")
crates/fdd_rules/src/runner.rs:366:        let df = ctx.sql(&format!("SELECT {sel} FROM history")).await?;
crates/fdd_rules/src/runner.rs:370:            if let Ok(wdf) = ctx.sql(&format!("SELECT {wsel} FROM weather")).await {
```

## Migration order (plan)

1. I1 — builders + CI lint ban + `fdd_rules/runner.rs`
2. I2 — `analytics/historian.rs` (sole owner in merge train)
3. I3 — #1010 agent custom-rule path (MCP; hardcoded tuners)

Do not rewrite cookbook bodies. Gate `40_no_id_heuristics.sh` must stay green.
