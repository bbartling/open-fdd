---
title: Milestone C acceptance
parent: Migration
nav_order: 24
---

# Milestone C acceptance

**Date:** 2026-07-28 · Branch `milestone-c/c1-c2-analytics-runtime`

Honest acceptance for the C1–C2 analytics runtime slice. Full Milestone C
(pandas retirement + DF MemTable + `sha-*` stack) remains open.

## Automated evidence

| Check | Command / evidence | Result |
|-------|-------------------|--------|
| C0 B adversarial | [`MILESTONE_B_ADVERSARIAL_VERIFICATION.md`](MILESTONE_B_ADVERSARIAL_VERIFICATION.md) | Done |
| Analytics unit tests | `cargo test -p openfdd-central analytics` | Required green on this branch |
| Clippy | `cargo clippy -p openfdd-central -- -D warnings` | Required clean |
| Engine label | Envelope `engine` == `central-analytics-v1` | Contract |
| Runtime compute | Δt integration tests in `runtime.rs` | Live |
| Economizer compute | Mixing / fan-off / ΔT tests in `economizer.rs` | Live |
| Sensor / schedule / mech / rcx / metering | Minimal compute + unit tests | Live (minimal) |
| DF SQL MemTable | — | **Follow-up** |
| Rule parity residual | [`MILESTONE_C_RULE_PARITY.md`](MILESTONE_C_RULE_PARITY.md) | Doc + fixtures; full harness residual |
| Full-stack `sha-*` | Operator / GHCR after merge | **Not claimed** on this branch tip alone |

## Family acceptance snapshot

| Family | `query_version` | Acceptance bar on this branch |
|--------|-----------------|-------------------------------|
| Runtime | `runtime-v1` | Inline samples → equipment run_hours |
| Economizer | `economizer-diagnostics-v1` | Inline points → metrics/points/skipped |
| Sensor health | `sensor-health-v1` | Inline points → coverage/flatline/stats |
| Schedule | `schedule-v1` | Occupied mask → hours; fan → after-hours |
| Mechanical cooling | `mechanical-cooling-v1` | Pump-only reject; compressor accept |
| RCx AHU | `rcx-ahu-v1` | sat_sp / duct_static_sp coverage fields |
| RCx VAV | `rcx-vav-v1` | Comfort ranking from zone_temp vs SP |
| Metering | `metering-v1` | Monthly sum of `{period, kwh}` |

## Manual / stack (deferred)

1. Publish GHCR `sha-<tip>` for central + UI after merge.
2. Smoke Overview runtime cards + RCx economizer against central.
3. Confirm no silent pandas fallback when central is down (visible error).

| Field | Value |
|-------|-------|
| Branch | `milestone-c/c1-c2-analytics-runtime` |
| Engine | `central-analytics-v1` |
| Notes | C0 done; C1–C2 runtime+economizer live; other families minimal compute |

## GitHub Actions

Rust Stack CI, React SPA, Cookbook parity, Docs, AppSec must stay green on
the PR that lands this branch.
