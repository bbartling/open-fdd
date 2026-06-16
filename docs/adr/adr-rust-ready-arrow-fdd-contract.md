# ADR: Rust-ready Arrow FDD contract

## Status

Accepted

## Context

Open-FDD runs supervisory FDD over historian telemetry from BACnet, Niagara, JSON API, and future connectors. PyArrow is the primary rule path; DataFusion SQL is an optional backend for SQL-authored rules and Rust migration prep.

## Decision

1. **PyArrow remains primary.** Rules implement `apply_faults_arrow(table, cfg, context=None)` and return Arrow boolean masks normalized to `ArrowRuleResult`.

2. **DataFusion SQL is optional.** Install via `open-fdd[datafusion]`. Rules declare `backend: datafusion_sql`, execute server-side only, read the registered `telemetry` Arrow table, and normalize to the same `ArrowRuleResult` shape.

3. **Common historian contract.** Drivers ingest `timestamp`, `site_id`, point columns, and `metadata.source` into Feather shards. Point metadata (`fdd_input`, `cross_source_semantic`, `equipment_id`) drives rule binding — not vendor-specific code in rule engines.

4. **Future Rust.** A Rust execution service may replace the Python Arrow/DataFusion wrappers behind the same table-in, boolean-mask-out contract. UI, commissioning, and driver orchestration stay in Python until migrated.

5. **Drivers must not bypass the contract.** No connector may emit a custom FDD result shape or row-loop rule path for production batch evaluation.

6. **No browser-side SQL.** DataFusion runs in the bridge process only.

7. **No pandas row-loop runtime on edge.** PyArrow columnar masks only for production FDD.

8. **Confirmation.** May use correctness-first Python streak loops today; future vectorized/window implementations must keep the same raw vs confirmed mask contract.

Authoring guide: [Rule authoring (v1)]({{ "/rule-authoring/" | relative_url }}) · [Arrow rule contract]({{ "/rule-authoring/arrow-rule-contract/" | relative_url }}).

## Consequences

- Rule Lab, batch FDD, and validation smokes share one mask contract.
- Confirmation window filters apply after raw masks for all backends.
- Vectorizing confirmation (window functions / Arrow kernels) is planned; correctness-first Python streak loops are acceptable for bench scale today.
