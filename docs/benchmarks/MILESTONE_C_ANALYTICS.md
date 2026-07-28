---
title: Milestone C analytics benchmarks
parent: Benchmarks
nav_order: 30
---

# Milestone C analytics benchmarks

**Date:** 2026-07-28 · Engine `central-analytics-v1` (pure Rust; DataFusion MemTable follow-up)

Placeholder structure for family wall-time / memory notes. Fill measured rows when
historian-backed loads and larger fixtures land. Unit tests today are micro-scale
inline fixtures only.

## Placeholder results table

| Family | Fixture scale | Rows / points | Wall time (ms) | Peak RSS (MB) | Engine | Notes |
|--------|---------------|---------------|----------------|---------------|--------|-------|
| Runtime | unit (13 pts / eq) | ~13 | _TBD_ | _TBD_ | `central-analytics-v1` | Δt integration + gap clip; see `runtime.rs` tests |
| Sensor health | unit (≤8 pts / series) | ~8 | _TBD_ | _TBD_ | `central-analytics-v1` | coverage / flatline / stats |
| Schedule | unit (2–3 mask pts) | ~3 | _TBD_ | _TBD_ | `central-analytics-v1` | occupied + after-hours fan hours |
| Mechanical cooling | unit (1–2 evidence rows) | ~2 | _TBD_ | _TBD_ | `central-analytics-v1` | evidence hierarchy gate only |
| Economizer | unit (1–N points) | ~1–N | _TBD_ | _TBD_ | `central-analytics-v1` | fan-on, ΔT gate, OA frac, MAT resid |
| RCx AHU | unit (coverage stub) | ~2 | _TBD_ | _TBD_ | `central-analytics-v1` | sat_sp / duct_static_sp coverage |
| RCx VAV | unit (comfort rank) | ~3 | _TBD_ | _TBD_ | `central-analytics-v1` | zone_temp vs setpoint |
| Metering | unit (3 monthly rows) | ~3 | _TBD_ | _TBD_ | `central-analytics-v1` | monthly kWh sum |

## Local microbench notes (from unit tests)

Commands (from repo root):

```bash
cargo test -p openfdd-central analytics -- --nocapture
```

Observed locally on this branch (developer workstation; not CI gate):

| Check | Observation |
|-------|-------------|
| `analytics::` unit suite | Completes in well under 1s wall on a warm build; no separate criterion harness yet |
| Runtime 1 h @ 5 min | Exact `run_hours == 1.0` (12 × 300 s) |
| Sensor flatline | `std == 0` with `n > 5` → `flatline_flag` |
| Mech cooling | Pump-only rejected; compressor/chiller accepted |
| Economizer 50% mix | OA fraction 50%, MAT residual ~0 with matched damper |

**Follow-up:** add small/medium/(large) Feather fixtures, measure wall + RSS, and
compare to pandas oracle tolerances once DF SQL MemTable paths exist.
