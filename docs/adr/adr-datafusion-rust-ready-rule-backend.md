# ADR: DataFusion as optional Rust-ready rule backend

## Status

Accepted — Open-FDD 3.1.0

## Context

Open-FDD v3 executes FDD rules over **Apache Arrow** tables. The primary contract is:

```python
apply_faults_arrow(table, cfg, context=None) -> BooleanArray | ChunkedArray
```

Operators and integrators author rules in Python/PyArrow. BACnet polling, bridge APIs, dashboard, MCP, and Docker deployment all consume normalized `ArrowRuleResult` payloads.

We want a migration path toward Rust/DataFusion components **without** rewriting the project in Rust or weakening the PyArrow contract.

## Decision

Add an **optional** second rule backend:

| Backend | Entry |
| --- | --- |
| `arrow` | `apply_faults_arrow(...)` (default, first-class) |
| `datafusion_sql` | Restricted `SELECT` over registered `telemetry` |

DataFusion is Apache Arrow-native and implemented in Rust. The Python `datafusion` package gives Open-FDD a clean seam where a future Rust service can replace or accelerate the wrapper while preserving the same result schema.

## Why

- Same Arrow memory model end-to-end
- SQL expressions are easy to read for simple threshold/CASE rules
- Compare mode can prove SQL masks match PyArrow before migration
- Optional extra — normal `pip install open-fdd` unchanged

## Non-goals (this milestone)

- No Rust rewrite
- No replacing PyArrow rules
- No pandas on edge runtime
- No arbitrary SQL console (injection-safe subset only)
- No changes to BACnet, bridge auth, or MCP unless required for tests

## Future path

**Phase A** — PyArrow + optional DataFusion Python backend (this ADR)

**Phase B** — Shared Arrow rule result contract across batch, Rules Lab, and reporting

**Phase C** — Optional Rust DataFusion crate/service replaces Python wrapper

**Phase D** — ML/graph analytics consume Arrow/Parquet outputs without changing the FDD rule contract

## Consequences

- CI adds a job with `pip install -e ".[test,dev,datafusion]"` for backend validation
- Rule store persists `sql` and `fault_column` separately from Python `code`
- Rules Lab gains backend selector; SQL executes server-side only
