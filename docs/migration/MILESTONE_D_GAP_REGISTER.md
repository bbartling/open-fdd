---
title: Milestone D gap register
parent: Migration
nav_order: 30
---

# Milestone D gap register

**Date:** 2026-07-28 · Branch `milestone-d/d5-closeout`

Tracks C→D gaps after D0–D5. Companion matrices:
[`vibe20_integration_matrix.md`](vibe20_integration_matrix.md),
[`MILESTONE_C_ANALYTICS_MATRIX.md`](MILESTONE_C_ANALYTICS_MATRIX.md).

| ID | Gap | Status | Notes |
|----|-----|--------|-------|
| D0 | Tip/GHCR audit + gap register + docs fortress | **Done** | #590; `sha-*` tip tags may lag `:nightly` |
| D1 | Historian → DataFusion analytics + UI cutover | **Improved** | #591 family DF bridges; plant descriptive counts only |
| D1b | Silent pandas Overview fallback | **Improved** | Oracle flag required (`OPENFDD_ANALYTICS_ORACLE=1`) |
| D2 | SQL rule parity mutation CI | **Done** | #592 path + logical keyword + fixture inventory |
| D2b | `PROVEN_MULTI_BUILDING` / BUILDING_100 | **Open** | Inventory only; multi-building not claimed |
| D3 | Job-native WattLab SoT | **Improved** | #593 central handoff + UI; zip additive |
| D4 | Restricted E+ runner | **Improved (stub)** | #593 policy + QUEUED persist; no Docker socket / in-process E+ |
| D4b | External runner claim + artifact attach loop | **Open** | Worker not wired |
| D5 | Vite `:5173` / escape-hatch scrub | **Improved** | Dev-stack → React `:8501` |
| C11 | Full pandas production retirement + `sha-*` soak | **Open** | Residual; GHCR `sha-e5bd0ffd` not yet pullable |
| A | `open_fdd.contracts` | **Deferred** | Milestone A residual |
