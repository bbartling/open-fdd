---
title: Milestone C closeout
parent: Migration
nav_order: 23
---

# Milestone C closeout

**Date:** 2026-07-28 · Branch `milestone-c/c1-c2-analytics-runtime`

## Executive summary

Milestone C introduces typed central `/api/analytics/*` envelopes and family
compute under engine label **`central-analytics-v1`**. C0 (B adversarial + README
invariants) is done. C1–C2 deliver **live** runtime and economizer diagnostics;
remaining families have **minimal real compute** (not empty schema stubs), with
honest warnings that DataFusion SQL / MemTable historian loads and full UI
cutover are follow-ups.

This is a **partial** Milestone C closeout for the C1–C2 runtime branch — not
full pandas retirement or `sha-*` full-stack acceptance.

## What is live

| Area | Status |
|------|--------|
| C0 adversarial B verification + README/cookbook honesty | **Done** |
| Analytics envelope + query_version contracts | **Done** |
| `POST /api/analytics/runtime` — Δt run hours + gap clip | **Live** |
| `POST /api/analytics/economizer` — fan-on, ΔT gate, OA frac, MAT resid | **Live** |
| Streamlit typed client for runtime + economizer | **Wired** (central preferred) |
| Sensor health — coverage / flatline / missingness / min-max-mean | **Minimal compute** |
| Schedule — occupied hours + optional after-hours fan hours | **Minimal compute** |
| Mechanical cooling — evidence hierarchy (pump/valve ≠ compressor) | **Minimal compute** |
| RCx AHU — sat_sp / duct_static_sp coverage stub fields | **Minimal compute** |
| RCx VAV — zone comfort ranking (zone_temp vs setpoint) | **Minimal compute** |
| Metering — monthly kWh sum | **Minimal compute** |

## Explicit follow-ups (not claimed done)

- DataFusion SQL / MemTable per family; bump `engine` only when SQL path is live
- Historian / job Feather load into analytics handlers
- Full Streamlit cutover for sensor / schedule / mech / RCx / metering; Overview economizer compact link
- Pandas production path retirement after cutover (oracle stays)
- SQL rule parity residual beyond fixture notes / mutation checklist
- Benchmark table fill for medium/large fixtures
- Full-stack immutable `sha-*` acceptance

## Engine honesty

Responses use `engine: "central-analytics-v1"`. Do **not** advertise
`engine: datafusion` until a family executes via DataFusion.

## Related

- [Analytics matrix](MILESTONE_C_ANALYTICS_MATRIX.md)
- [Acceptance](MILESTONE_C_ACCEPTANCE.md)
- [Rule parity](MILESTONE_C_RULE_PARITY.md)
- [Benchmarks](../benchmarks/MILESTONE_C_ANALYTICS.md)
