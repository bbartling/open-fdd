# H8 — Continuous AFDD scheduler / findings / API

Status: active after H7 merge `07f59e98`.

This checkpoint starts H8 from updated `master`; H8 is not stacked on the H7 branch.

## Required contract

- explicit `bulk` vs `continuous` operating modes
- scheduling interval independent from rolling lookback
- continuous rolling window ends at the latest successfully persisted eligible telemetry watermark written by H7
- overlapping windows are intentional for late-arriving telemetry
- persisted scheduler checkpoint survives restart
- prevent overlapping AFDD cycles for the same scope
- after downtime, run one catch-up cycle when due rather than replaying every missed tick
- manual run-now and scheduled runs share the same execution engine
- historical backfill is explicit and chunked
- preserve existing finding contracts while adding episode continuity/dedup where needed
- isolate building/rule failures where existing execution contracts safely allow it

## Target configuration

```text
OPENFDD_AFDD_MODE=bulk|continuous
OPENFDD_AFDD_INTERVAL_MINUTES=60
OPENFDD_AFDD_LOOKBACK_VALUE=24
OPENFDD_AFDD_LOOKBACK_UNIT=hours
```

Bulk CSV/history import must never implicitly enable recurring AFDD.

## First implementation slice

1. Add strict H8 configuration parsing and validation with `bulk` as the safe default.
2. Load H7's persisted latest-telemetry watermark from the configured canonical storage backend.
3. Define persisted scheduler checkpoint and deterministic due/catch-up window calculation.
4. Add per-scope non-overlap guard and one shared cycle execution entry point for scheduled/run-now calls.
5. Expose read-only scheduler/cycle status API needed by H9 before adding UI controls.

## Gates

Do not merge H8 until its exact final head passes FDD DataFusion Engine CI, Rust Stack CI, AppSec, docs-guard, Stack Security Guards, and has no unresolved review threads. Keep historian/central ingress private-only and do not add a traditional database as canonical historian or scheduler state store.
