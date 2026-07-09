# Open-FDD port — finish plan

**Status:** Core port **complete** on `port-vibe19-rust-datafusion-engine`.  
**Remaining:** CI hygiene, push, live parity re-verify.

## Done (definition of done met)

- [x] Rust workspace builds; fmt / clippy / 23 tests pass
- [x] 19 SQL rules + `registry.yaml` ported
- [x] `openfdd_cli`: validate, ingest, run-rules, compare, benchmark
- [x] BUILDING_100: validate + 19/19 run-rules (local)
- [x] Cookbook preserved; `COOKBOOK_TO_SQL_RULES.md` added
- [x] Docs + `AGENTS.md` + port inventory
- [x] Gutted edge/dashboard removed (checkpoint `4fe1dc99`)
- [x] Source vibe repo untouched

## Leftover (this pass)

| # | Task | Priority | Owner |
|---|------|----------|-------|
| 1 | Remove/disable stale GH Actions (`edge/`, `workspace/dashboard/`) | P0 | done |
| 2 | Fresh BUILDING_100 compare (re-export oracle + compare) | P1 | done |
| 3 | Push `port-vibe19-rust-datafusion-engine` to origin | P0 | done |
| 4 | Open PR → `master` | P2 | human |

**Live verify (2026-07-09):** fresh ingest + compare → **368 pass / 0 fail / 11 skipped** @ 0.5h.

## Deferred (not blocking port)

- Rename `fdd_*` crates → `openfdd_*`
- HTTP API + React production UI
- Slim standalone Python oracle package
- Merge port branch to `master`

## Verify after finish

```powershell
cd C:\Users\ben\Documents\open-fdd
cargo test --workspace
cargo run -p fdd_cli --release -- validate --data-root examples/sample_data --building BUILDING_FIXTURE
# BUILDING_100 compare → 368 pass / 0 fail @ 0.5h
```
