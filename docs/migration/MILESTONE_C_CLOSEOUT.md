---
title: Milestone C closeout
parent: Migration
nav_order: 23
---

# Milestone C closeout

**Date:** 2026-07-28 · Tip `7fed6fb8` (#589)

## Executive summary

Milestone C introduces typed central `/api/analytics/*` envelopes and family
compute under engine label **`central-analytics-v1`**. C0 (B adversarial + README
invariants) is done. C1–C2 deliver **live** runtime and economizer diagnostics;
remaining families have **minimal real compute** (not empty schema stubs), with
honest warnings that DataFusion SQL / MemTable historian loads and full UI
cutover are follow-ups.

This is a **partial** Milestone C closeout — not full pandas retirement or
`sha-*` full-stack acceptance. Gap register for Milestone D:
[`MILESTONE_C_TO_D_GAP_REGISTER.md`](MILESTONE_C_TO_D_GAP_REGISTER.md).

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
| RCx AHU / VAV / plant | **Minimal compute** |
| Metering — monthly kWh sum | **Minimal compute** |

## GHCR

| Field | Value |
|-------|-------|
| Open-FDD SHA | `7fed6fb8` |
| Expected tags | `ghcr.io/bbartling/openfdd-{central,ui}:sha-7fed6fb8` and `:nightly` |
| Notes | Publish workflow triggered by #589; confirm digests when Actions green |

## Explicit follow-ups (Milestone D / finish C)

- DataFusion SQL / MemTable per family; bump `engine` only when SQL path is live
- Historian / job Feather load into analytics handlers
- Full Streamlit cutover; pandas production retirement (oracle stays)
- SQL rule parity + mutation checks; filled benches; `sha-*` soak
- Phase 8 WattLab job-native + restricted EnergyPlus runner

## Engine honesty

Responses use `engine: "central-analytics-v1"`. Do **not** advertise
`engine: datafusion` until a family executes via DataFusion.

## Related

- [C→D gap register](MILESTONE_C_TO_D_GAP_REGISTER.md)
- [Analytics matrix](MILESTONE_C_ANALYTICS_MATRIX.md)
- [Acceptance](MILESTONE_C_ACCEPTANCE.md)
- [Rule parity](MILESTONE_C_RULE_PARITY.md)
- [Benchmarks](../benchmarks/MILESTONE_C_ANALYTICS.md)
