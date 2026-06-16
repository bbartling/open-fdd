---
title: Rust readiness checklist
parent: Rule authoring (v1)
nav_order: 5
---

# Rust readiness checklist

Open-FDD v1 keeps a **table-in, boolean-mask-out** contract so a future Rust or DataFusion-native executor can replace Python wrappers without changing Rule Lab metadata or driver ingest.

Use this checklist when authoring or reviewing rules for stable v1 and Rust migration prep.

## Rule style

- [ ] **No pandas** in edge fault rules — PyArrow columns only
- [ ] **No NumPy** for core detection logic (optional in central analytics extras only)
- [ ] **No Python row loops** over samples for hot-path fault detection — use `pyarrow.compute` and `open_fdd.arrow_runtime.windows`
- [ ] **Arrow arrays in, boolean mask out** — length equals input row count
- [ ] **Explicit config schema** — document `cfg` keys in rule module docstring
- [ ] **Deterministic null behavior** — document how missing columns / nulls are treated
- [ ] **No hidden global state** — pure functions of `(table, cfg, context)`
- [ ] **Stable fault-code metadata** — letter codes from [fault catalog]({{ "/fault-codes/" | relative_url }})
- [ ] **Small fixture tests** — fixed `pa.table(...)` inputs with expected mask slices
- [ ] **DataFusion SQL rules stay restricted** — single `SELECT` from `telemetry`, boolean `fault` column, no DDL/DML

## Backend choice

| Prefer PyArrow | Prefer DataFusion SQL |
|----------------|----------------------|
| Rolling windows, hunting, flatline | Simple threshold / CASE |
| Schedule / occupancy gating | Operator-readable SQL preview |
| Sensor profile helpers | Parity proof before Rust port |
| ML feature prep (future) | Stateless row-wise logic |

See [PyArrow vs DataFusion decision table]({{ "/rule-cookbook/expression-cookbook/" | relative_url }}#pyarrow-vs-datafusion-sql).

## Do not use DataFusion SQL for

- Complex rolling windows or resample-style logic
- PID / control hunting with stateful window counts (use PyArrow helpers)
- Custom helper-heavy HVAC logic
- ML feature preparation pipelines
- Arbitrary file joins or external tables
- Browser-side execution
- Pandas-style row iteration

## Confirmation and evidence

- [ ] Raw mask produced by rule; confirmation via `min_true_rows` / `min_elapsed_minutes` in `cfg`
- [ ] Batch results include execution evidence (`computation_path`, backend id) for smokes

## Packaging

- [ ] Edge Docker image includes PyArrow runtime
- [ ] DataFusion optional: `pip install 'open-fdd[datafusion]'` — matches `pyproject.toml` `[project.optional-dependencies] datafusion`

## Related ADRs

- [ADR: Rust-ready Arrow FDD contract]({{ "/adr/adr-rust-ready-arrow-fdd-contract/" | relative_url }})
- [ADR: DataFusion Rust-ready rule backend]({{ "/adr/adr-datafusion-rust-ready-rule-backend/" | relative_url }})
