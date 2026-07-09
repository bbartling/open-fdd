# Port from Vibe19 — inventory

**Source:** `py-bacnet-stacks-playground/vibe_code_apps_19` @ `develop` (368 pass parity)  
**Destination:** `open-fdd` branch `port-vibe19-rust-datafusion-engine`  
**Date:** 2026-07-09

## Naming decision

First port keeps internal crate names `fdd_*` (from App 19 `rust_fdd_core/`). CLI binary is **`openfdd_cli`**. Future rename to `openfdd_*` crates is documented but deferred to avoid a large mechanical diff on day one.

## Ported

| Source | Destination | Notes |
| --- | --- | --- |
| `rust_fdd_core/Cargo.toml`, `Cargo.lock` | repo root | Workspace root |
| `rust_fdd_core/crates/*` | `crates/*` | 7 crates: core, csv, store, sql, rules, bench, cli |
| `sql_rules/` | `sql_rules/` | 19 rules + `registry.yaml` |
| `rule_tuning/` | `rule_tuning/` | defaults scaffold |
| `vibe19_agent_spec/benchmarks/` | `docs/benchmarks/` | BUILDING_100 parity report |
| `vibe19_agent_spec/docs/` | `docs/migration/vibe19/` | Stage 2–4 specs |
| `fdd_app/export_pandas_oracle.py` | `tools/python_oracle/` | Optional test oracle |
| `fdd_app/debug_rule_parity.py` | `tools/python_oracle/` | Sample-level debug |
| `validate_data.py` | `tools/python_oracle/` | Data tree GO check |
| `AGENTS.md` | `AGENTS.md` | Adapted for Open-FDD |

## Preserved (Open-FDD)

| Path | Purpose |
| --- | --- |
| `docs/rules/cookbook/` | Online expression rule cookbook |
| `docs/rules/` | Rules index, DataFusion SQL docs |
| `docs/modeling/` | Haystack modeling docs |
| `LICENSE`, `VERSION`, `README.md` | Project metadata |
| `.github/workflows/` | Updated for new workspace |
| `tests/selenium/` | Legacy frontend rig (may retire later) |
| `os/` | Edge OS notes |

## Removed (checkpoint `4fe1dc99`)

| Area | Reason |
| --- | --- |
| `edge/` | Old speculative Rust edge app — replaced by App 19 engine |
| `workspace/dashboard/` | React UI stub — future rewrite per FRONTEND plan |
| Docker compose / Caddy / MCP stacks | Not part of Rust-first port |
| `docs/archive/`, `docs/agent/`, drivers/web-app docs | Contradict gutted architecture |

See `docs/PORT_FROM_VIBE19_REMOVALS.md`.

## Adaptation risks

| Risk | Mitigation |
| --- | --- |
| Crate rename breaks paths | Keep `fdd_*` names initially |
| Python oracle needs full cookbook | Document as optional; compare uses pre-exported JSON |
| BUILDING_100 data external | `.cache/` gitignored; benchmark doc ships results |
| Old CI references `edge/` | New `ci.yml` targets workspace only |

## Test plan

1. `cargo fmt --check`, `clippy -D warnings`, `cargo test --workspace`
2. CLI on `examples/sample_data/BUILDING_FIXTURE`
3. BUILDING_100 if `HVAC_DATA_ROOT` available locally
4. Registry: all SQL files referenced in `registry.yaml` exist
5. Optional: Python oracle compare when full stack available
