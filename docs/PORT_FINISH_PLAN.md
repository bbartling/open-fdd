# Port finish plan — additive integration (PR #477)

**Status:** Integration path is **PR #477** (`cleanup/integrate-rust-port-into-master`), not a direct merge of `port-vibe19-rust-datafusion-engine`.

## Why additive

| Branch | Strategy | Production edge/MCP |
| --- | --- | --- |
| `port-vibe19-rust-datafusion-engine` | Standalone engine tree; **removed** `edge/`, Docker, dashboard | **Destroyed** — do not merge |
| `cleanup/integrate-rust-port-into-master` (PR #477) | Cherry-pick/add FDD crates + SQL + docs **into** current `master` | **Preserved** |

## PR #477 delivers

- [x] `crates/fdd_*` (7 crates)
- [x] `sql_rules/` (19 rules + registry)
- [x] `rule_tuning/`
- [x] `tools/python_oracle/` (test/oracle only)
- [x] `.github/workflows/fdd-engine-ci.yml`
- [x] Port docs under `docs/migration/vibe19/`, `docs/cookbook/`
- [x] Unified workspace `Cargo.toml` (edge + mcp + fdd crates)
- [x] Production `edge/`, `mcp/`, `workspace/dashboard/`, Docker stacks unchanged

## After merge

1. Delete `port-vibe19-rust-datafusion-engine` (engine work is on master via #477)
2. Delete `cleanup/integrate-rust-port-into-master`
3. Continue React/TS cutover on `workspace/dashboard/` → `frontend/` in Docker image

## Verify

```powershell
cargo test -p fdd_core -p fdd_csv -p fdd_store -p fdd_sql -p fdd_rules -p fdd_bench -p fdd_cli
cargo run -p fdd_cli --release -- validate --data-root examples/sample_data --building BUILDING_FIXTURE
```
